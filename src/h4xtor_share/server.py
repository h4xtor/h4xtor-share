from __future__ import annotations

import asyncio
import re
import secrets
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiofiles
from aiohttp import web

from h4xtor_share import __version__
from h4xtor_share.config import Config
from h4xtor_share.models import (
    DESKTOP_CAPABILITIES,
    ClipboardReceived,
    FileReceived,
    FolderReceived,
    LinkReceived,
    PairingPrompt,
    Peer,
    PeerForgotten,
    PeerPaired,
    TransferProgress,
    WifiDirectOffer,
)

PAIRING_TTL_SECONDS = 120
QR_SECRET_TTL_SECONDS = 300
FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
DEVICE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
MAX_URL_LENGTH = 8192
CHUNK_SIZE = 1024 * 1024
TRANSFER_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
MAX_FOLDER_ENTRIES = 10_000
MAX_RELATIVE_SEGMENTS = 64
STALE_TEMP_AGE_SECONDS = 24 * 60 * 60


INVALID_NAME_CHARACTERS = '<>:"|?*'
_RESERVED_WINDOWS_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
MAX_NAME_LENGTH = 240


def safe_file_name(value: str) -> str:
    name = Path(value.replace("\\", "/")).name.strip()
    name = "".join(
        char
        for char in name
        if ord(char) >= 32 and char not in INVALID_NAME_CHARACTERS
    )
    name = name.rstrip(" .")
    if not name or name in {".", ".."}:
        raise ValueError("Invalid file name.")
    if name.split(".")[0].upper() in _RESERVED_WINDOWS_NAMES:
        name = f"_{name}"
    return name[:MAX_NAME_LENGTH]


def unique_destination(directory: Path, file_name: str) -> Path:
    candidate = directory / file_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        alternative = directory / f"{stem} ({index}){suffix}"
        if not alternative.exists():
            return alternative
        index += 1


def safe_relative_path(value: str) -> str:
    """Sanitize a relative path into safe, nested directory segments.

    Every segment is passed through ``safe_file_name`` so traversal attempts
    (``../``, absolute paths, reserved Windows names) are neutralized and the
    result stays valid on Windows, macOS and Linux. Returns a forward-slash
    joined path relative to the incoming folder.
    """
    normalized = value.strip().replace("\\", "/").lstrip("/")
    segments = [
        safe_file_name(part)
        for part in normalized.split("/")
        if part and part != "."
    ]
    if not segments or any(part in {".", ".."} for part in segments):
        raise ValueError("Invalid relative path.")
    if len(segments) > MAX_RELATIVE_SEGMENTS:
        raise ValueError("Relative path has too many segments.")
    return "/".join(segments)


def remote_address(request: web.Request) -> str:
    """IPv4 address of the connecting peer (IPv4-mapped IPv6 is unwrapped)."""
    remote = request.remote or ""
    if remote.startswith("::ffff:"):
        remote = remote.removeprefix("::ffff:")
    return remote


def is_safe_url(url: str) -> bool:
    if not url or len(url) > MAX_URL_LENGTH or any(ch.isspace() for ch in url):
        return False
    lowered = url.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


class ShareServer:
    def __init__(
        self,
        config: Config,
        ssl_context: Any,
        fingerprint: str,
        event_callback: Callable[[object], None],
    ) -> None:
        self.config = config
        self.ssl_context = ssl_context
        self.fingerprint = fingerprint
        self.event_callback = event_callback
        self.pending_pairings: dict[str, dict[str, Any]] = {}
        self.transfers: dict[str, dict[str, Any]] = {}
        self.folders: dict[str, dict[str, Any]] = {}
        self.qr_secrets: dict[str, float] = {}
        self.capabilities: tuple[str, ...] = DESKTOP_CAPABILITIES
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.app = web.Application(client_max_size=0)
        self.app.add_routes(
            [
                web.get("/api/v1/info", self.info),
                web.get("/api/v1/ping", self.ping),
                web.post("/api/v1/pair/request", self.pair_request),
                web.post("/api/v1/pair/confirm", self.pair_confirm),
                web.post("/api/v1/pair/qr", self.pair_qr),
                web.post("/api/v1/unpair", self.unpair),
                web.post("/api/v1/link", self.link),
                web.post("/api/v1/wifi-direct/offer", self.wifi_direct_offer),
                web.post("/api/v1/clipboard", self.clipboard),
                web.post("/api/v1/files/init", self.file_init),
                web.put("/api/v1/files/{transfer_id}", self.file_upload),
                web.post("/api/v1/folders/init", self.folder_init),
                web.put("/api/v1/folders/{folder_id}/{file_id}", self.folder_upload),
                web.post("/api/v1/folders/complete", self.folder_complete),
            ]
        )

    async def start(self) -> None:
        self.config.incoming_directory.mkdir(parents=True, exist_ok=True)
        self._sweep_stale_temp()
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(
            self.runner,
            host="0.0.0.0",
            port=self.config.port,
            ssl_context=self.ssl_context,
        )
        await self.site.start()

    def _sweep_stale_temp(self) -> None:
        """Remove abandoned ``.part`` files and staging directories.

        Interrupted transfers leave partial data on disk. Anything older than
        ``STALE_TEMP_AGE_SECONDS`` belongs to a transfer that can no longer be
        resumed, so it is reclaimed without touching active or completed files.
        """
        incoming = self.config.incoming_directory
        if not incoming.exists():
            return
        cutoff = time.time() - STALE_TEMP_AGE_SECONDS
        for candidate in incoming.iterdir():
            try:
                if not candidate.name.startswith(".h4xtor-"):
                    continue
                if candidate.stat().st_mtime < cutoff:
                    if candidate.is_dir():
                        shutil.rmtree(candidate, ignore_errors=True)
                    else:
                        candidate.unlink()
            except OSError:
                continue

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
        self.runner = None
        self.site = None

    async def info(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "protocol": 1,
                "device_id": self.config.device_id,
                "name": self.config.device_name,
                "platform": self.config.platform_name,
                "port": self.config.port,
                "fingerprint": self.fingerprint,
                "capabilities": list(self.capabilities),
                "version": __version__,
            }
        )

    async def ping(self, request: web.Request) -> web.Response:
        """Unauthenticated liveness probe used for status LEDs and signal bars.

        The round-trip time measured by the caller doubles as a coarse link
        quality signal without needing Wi-Fi APIs on every platform.
        """
        return web.json_response(
            {"pong": True, "device_id": self.config.device_id}
        )

    async def pair_request(self, request: web.Request) -> web.Response:
        payload = await request.json()
        peer_id = str(payload.get("device_id") or "").strip()
        peer_name = str(payload.get("name") or "Unknown device").strip()[:80]
        if not re.fullmatch(r"[a-f0-9]{32}", peer_id):
            raise web.HTTPBadRequest(text="Invalid device id.")

        pairing_id = uuid.uuid4().hex
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = time.time() + PAIRING_TTL_SECONDS
        self.pending_pairings[pairing_id] = {
            "peer_id": peer_id,
            "peer_name": peer_name,
            "code": code,
            "expires_at": expires_at,
        }
        self.event_callback(
            PairingPrompt(
                pairing_id=pairing_id,
                peer_id=peer_id,
                peer_name=peer_name,
                code=code,
                expires_at=expires_at,
            )
        )
        return web.json_response(
            {
                "pairing_id": pairing_id,
                "expires_in": PAIRING_TTL_SECONDS,
            }
        )

    async def pair_confirm(self, request: web.Request) -> web.Response:
        payload = await request.json()
        pairing_id = str(payload.get("pairing_id") or "")
        code = str(payload.get("code") or "")
        pending = self.pending_pairings.pop(pairing_id, None)
        if not pending or pending["expires_at"] < time.time():
            raise web.HTTPUnauthorized(text="Pairing request expired.")
        if not secrets.compare_digest(pending["code"], code):
            raise web.HTTPUnauthorized(text="Incorrect pairing code.")
        return self._complete_pairing(
            request,
            pending["peer_id"],
            pending["peer_name"],
            payload.get("reverse"),
        )

    # -- QR pairing ----------------------------------------------------------
    def create_qr_secret(self, ttl_seconds: float = QR_SECRET_TTL_SECONDS) -> str:
        """Return a one-time secret embedded in the pairing QR code."""
        now = time.time()
        self.qr_secrets = {
            secret: expires for secret, expires in self.qr_secrets.items() if expires > now
        }
        secret = secrets.token_urlsafe(18)
        self.qr_secrets[secret] = now + ttl_seconds
        return secret

    def revoke_qr_secret(self, secret: str) -> None:
        self.qr_secrets.pop(secret, None)

    async def pair_qr(self, request: web.Request) -> web.Response:
        """Pair instantly with a device that scanned this device's QR code.

        The QR code carries this device's certificate fingerprint (so the
        scanner pins TLS from the very first byte) and a short-lived one-time
        secret that replaces the six-digit code.
        """
        payload = await request.json()
        secret = str(payload.get("secret") or "")
        peer_id = str(payload.get("device_id") or "").strip()
        peer_name = str(payload.get("name") or "Unknown device").strip()[:80]
        if not DEVICE_ID_PATTERN.fullmatch(peer_id):
            raise web.HTTPBadRequest(text="Invalid device id.")
        match = next(
            (
                known
                for known in list(self.qr_secrets)
                if secrets.compare_digest(known, secret)
            ),
            None,
        )
        if match is None or self.qr_secrets.get(match, 0) < time.time():
            raise web.HTTPUnauthorized(text="QR code expired. Show a new code.")
        del self.qr_secrets[match]
        if not isinstance(payload.get("reverse"), dict):
            raise web.HTTPBadRequest(text="QR pairing requires reverse credentials.")
        return self._complete_pairing(request, peer_id, peer_name, payload.get("reverse"))

    def _complete_pairing(
        self,
        request: web.Request,
        peer_id: str,
        peer_name: str,
        reverse: object,
    ) -> web.Response:
        token = secrets.token_urlsafe(48)
        self.config.trust_inbound_peer(peer_id, token, peer_name)
        mutual = False
        if isinstance(reverse, dict):
            peer = self._accept_reverse(request, peer_id, peer_name, reverse)
            if peer is not None:
                mutual = True
                self.event_callback(PeerPaired(peer=peer, mutual=True))
        return web.json_response(
            {
                "token": token,
                "device_id": self.config.device_id,
                "name": self.config.device_name,
                "fingerprint": self.fingerprint,
                "platform": self.config.platform_name,
                "port": self.config.port,
                "capabilities": list(self.capabilities),
                "mutual": mutual,
            }
        )

    def _accept_reverse(
        self,
        request: web.Request,
        peer_id: str,
        peer_name: str,
        reverse: dict[str, Any],
    ) -> Peer | None:
        """Store the initiator's credentials so this device can send back."""
        token = reverse.get("token")
        fingerprint = str(reverse.get("fingerprint") or "").lower()
        if not isinstance(token, str) or len(token) < 16:
            return None
        if not FINGERPRINT_PATTERN.fullmatch(fingerprint):
            return None
        try:
            port = int(reverse.get("port") or self.config.port)
        except (TypeError, ValueError):
            return None
        if not 0 < port < 65536:
            return None
        address = remote_address(request)
        if not address:
            return None
        capabilities = reverse.get("capabilities") or []
        peer = Peer(
            device_id=peer_id,
            name=peer_name,
            address=address,
            port=port,
            fingerprint=fingerprint,
            platform=str(reverse.get("platform") or "unknown")[:32],
            transport="lan",
            capabilities=tuple(str(item)[:32] for item in capabilities[:32])
            if isinstance(capabilities, list)
            else (),
        )
        self.config.trust_outbound_peer(peer_id, token, fingerprint, peer_name)
        self.config.remember_peer(peer)
        return peer

    def authenticate(self, request: web.Request) -> tuple[str, str]:
        peer_id = request.headers.get("X-H4xtor-Device", "")
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise web.HTTPUnauthorized(text="Missing bearer token.")
        token = authorization.removeprefix("Bearer ").strip()
        if not self.config.validate_inbound_token(peer_id, token):
            raise web.HTTPUnauthorized(text="Peer is not trusted.")
        entry = self.config.data.get("trusted_peers", {}).get(peer_id, {})
        peer_name = str(entry.get("name") or peer_id)
        return peer_id, peer_name

    async def clipboard(self, request: web.Request) -> web.Response:
        peer_id, peer_name = self.authenticate(request)
        payload = await request.json()
        text = payload.get("text")
        if not isinstance(text, str):
            raise web.HTTPBadRequest(text="Clipboard payload must contain text.")
        self.event_callback(
            ClipboardReceived(peer_id=peer_id, peer_name=peer_name, text=text)
        )
        return web.json_response({"accepted": True, "characters": len(text)})

    async def unpair(self, request: web.Request) -> web.Response:
        peer_id, peer_name = self.authenticate(request)
        self.config.forget_peer(peer_id)
        self.event_callback(PeerForgotten(peer_id=peer_id, peer_name=peer_name))
        return web.json_response({"forgotten": True})

    async def link(self, request: web.Request) -> web.Response:
        peer_id, peer_name = self.authenticate(request)
        payload = await request.json()
        url = str(payload.get("url") or "").strip()
        if not is_safe_url(url):
            raise web.HTTPBadRequest(text="Only http(s) links can be pushed.")
        self.event_callback(LinkReceived(peer_id=peer_id, peer_name=peer_name, url=url))
        return web.json_response({"accepted": True})

    async def wifi_direct_offer(self, request: web.Request) -> web.Response:
        peer_id, peer_name = self.authenticate(request)
        payload = await request.json()
        ssid = str(payload.get("ssid") or "")
        passphrase = str(payload.get("passphrase") or "")
        owner = str(payload.get("owner_address") or "192.168.49.1")
        try:
            port = int(payload.get("port") or self.config.port)
        except (TypeError, ValueError) as error:
            raise web.HTTPBadRequest(text="Invalid port.") from error
        if not 0 < len(ssid) <= 32 or not 8 <= len(passphrase) <= 63:
            raise web.HTTPBadRequest(text="Invalid Wi-Fi Direct credentials.")
        if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", owner):
            raise web.HTTPBadRequest(text="Invalid group owner address.")
        self.event_callback(
            WifiDirectOffer(
                peer_id=peer_id,
                peer_name=peer_name,
                ssid=ssid,
                passphrase=passphrase,
                owner_address=owner,
                port=port,
            )
        )
        return web.json_response({"accepted": True})

    async def file_init(self, request: web.Request) -> web.Response:
        peer_id, peer_name = self.authenticate(request)
        payload = await request.json()
        transfer_id = str(payload.get("transfer_id") or "")
        if not TRANSFER_ID_PATTERN.fullmatch(transfer_id):
            raise web.HTTPBadRequest(text="Invalid transfer id.")
        try:
            file_name = safe_file_name(str(payload.get("name") or ""))
            total_size = int(payload.get("size"))
        except (TypeError, ValueError) as error:
            raise web.HTTPBadRequest(text="Invalid file metadata.") from error
        if total_size < 0:
            raise web.HTTPBadRequest(text="Invalid file size.")

        incoming = self.config.incoming_directory
        incoming.mkdir(parents=True, exist_ok=True)
        part_path = incoming / f".h4xtor-{transfer_id}.part"
        offset = part_path.stat().st_size if part_path.exists() else 0
        if offset > total_size:
            part_path.unlink()
            offset = 0
        self.transfers[transfer_id] = {
            "peer_id": peer_id,
            "peer_name": peer_name,
            "name": file_name,
            "size": total_size,
            "part_path": part_path,
        }
        return web.json_response(
            {
                "transfer_id": transfer_id,
                "offset": offset,
            }
        )

    async def file_upload(self, request: web.Request) -> web.Response:
        self.authenticate(request)
        transfer_id = request.match_info["transfer_id"]
        transfer = self.transfers.get(transfer_id)
        if not transfer:
            raise web.HTTPNotFound(text="Transfer was not initialized.")
        try:
            requested_offset = int(request.headers.get("X-H4xtor-Offset", "-1"))
        except ValueError as error:
            raise web.HTTPBadRequest(text="Invalid transfer offset.") from error

        part_path: Path = transfer["part_path"]
        actual_offset = part_path.stat().st_size if part_path.exists() else 0
        if requested_offset != actual_offset:
            raise web.HTTPConflict(
                text=str(actual_offset),
                headers={"X-H4xtor-Offset": str(actual_offset)},
            )

        async with aiofiles.open(part_path, "ab") as output:
            async for chunk in request.content.iter_chunked(CHUNK_SIZE):
                if not chunk:
                    continue
                await output.write(chunk)
                actual_offset += len(chunk)
                if actual_offset > transfer["size"]:
                    raise web.HTTPBadRequest(text="Received more bytes than declared.")
                self.event_callback(
                    TransferProgress(
                        transfer_id=transfer_id,
                        file_name=transfer["name"],
                        sent=actual_offset,
                        total=transfer["size"],
                        direction="receive",
                        peer_name=transfer["peer_name"],
                    )
                )

        if actual_offset == transfer["size"]:
            destination = unique_destination(
                self.config.incoming_directory,
                transfer["name"],
            )
            await asyncio.to_thread(part_path.replace, destination)
            self.event_callback(
                FileReceived(
                    peer_id=transfer["peer_id"],
                    peer_name=transfer["peer_name"],
                    path=destination,
                    size=transfer["size"],
                    transfer_id=transfer_id,
                )
            )
            del self.transfers[transfer_id]

        return web.json_response(
            {
                "transfer_id": transfer_id,
                "offset": actual_offset,
                "complete": actual_offset == transfer["size"],
            }
        )

    async def folder_init(self, request: web.Request) -> web.Response:
        """Begin a directory transfer.

        The sender supplies a manifest: the folder name and one entry per file
        with its own transfer id, sanitized relative path and byte size. The
        receiver creates an isolated staging directory and reports the existing
        resume offset of every partial file already on disk.
        """
        peer_id, peer_name = self.authenticate(request)
        payload = await request.json()
        folder_id = str(payload.get("folder_id") or "")
        if not TRANSFER_ID_PATTERN.fullmatch(folder_id):
            raise web.HTTPBadRequest(text="Invalid folder id.")
        try:
            folder_name = safe_file_name(str(payload.get("name") or ""))
        except ValueError as error:
            raise web.HTTPBadRequest(text="Invalid folder name.") from error

        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise web.HTTPBadRequest(text="Folder must contain at least one file.")
        if len(raw_entries) > MAX_FOLDER_ENTRIES:
            raise web.HTTPBadRequest(text="Folder contains too many files.")

        files: dict[str, dict[str, Any]] = {}
        for entry in raw_entries:
            try:
                file_id = str(entry["id"])
                relative = safe_relative_path(str(entry["path"]))
                size = int(entry["size"])
            except (KeyError, TypeError, ValueError) as error:
                raise web.HTTPBadRequest(text="Invalid folder entry.") from error
            if not TRANSFER_ID_PATTERN.fullmatch(file_id) or size < 0:
                raise web.HTTPBadRequest(text="Invalid folder entry.")
            if file_id in files:
                raise web.HTTPBadRequest(text="Duplicate folder entry.")
            files[file_id] = {"path": relative, "size": size}

        incoming = self.config.incoming_directory
        incoming.mkdir(parents=True, exist_ok=True)
        staging = incoming / f".h4xtor-folder-{folder_id}"
        staging.mkdir(parents=True, exist_ok=True)

        offsets: list[dict[str, Any]] = []
        for file_id, metadata in files.items():
            part = staging / f".h4xtor-{file_id}.part"
            offset = part.stat().st_size if part.exists() else 0
            if offset > metadata["size"]:
                part.unlink()
                offset = 0
            metadata["part"] = part
            offsets.append({"id": file_id, "path": metadata["path"], "offset": offset})

        self.folders[folder_id] = {
            "peer_id": peer_id,
            "peer_name": peer_name,
            "name": folder_name,
            "staging": staging,
            "files": files,
            "done": set(),
            "received": {entry["id"]: entry["offset"] for entry in offsets},
            "total": sum(metadata["size"] for metadata in files.values()),
        }
        return web.json_response(
            {
                "folder_id": folder_id,
                "name": folder_name,
                "entries": offsets,
            }
        )

    async def folder_upload(self, request: web.Request) -> web.Response:
        self.authenticate(request)
        folder_id = request.match_info["folder_id"]
        file_id = request.match_info["file_id"]
        folder = self.folders.get(folder_id)
        if not folder:
            raise web.HTTPNotFound(text="Folder was not initialized.")
        if file_id in folder["done"]:
            raise web.HTTPConflict(text="File already received.")
        metadata = folder["files"].get(file_id)
        if not metadata:
            raise web.HTTPNotFound(text="Folder entry was not initialized.")

        try:
            requested_offset = int(request.headers.get("X-H4xtor-Offset", "-1"))
        except ValueError as error:
            raise web.HTTPBadRequest(text="Invalid transfer offset.") from error

        part_path: Path = metadata["part"]
        actual_offset = part_path.stat().st_size if part_path.exists() else 0
        if requested_offset != actual_offset:
            raise web.HTTPConflict(
                text=str(actual_offset),
                headers={"X-H4xtor-Offset": str(actual_offset)},
            )

        # Progress is reported for the folder as a whole, not per file, so a
        # folder with thousands of files shows up as one transfer.
        async with aiofiles.open(part_path, "ab") as output:
            async for chunk in request.content.iter_chunked(CHUNK_SIZE):
                if not chunk:
                    continue
                await output.write(chunk)
                actual_offset += len(chunk)
                if actual_offset > metadata["size"]:
                    raise web.HTTPBadRequest(text="Received more bytes than declared.")
                folder["received"][file_id] = actual_offset
                self.event_callback(
                    TransferProgress(
                        transfer_id=folder_id,
                        file_name=folder["name"],
                        sent=sum(folder["received"].values()),
                        total=folder["total"],
                        direction="receive",
                        peer_name=folder["peer_name"],
                    )
                )

        if actual_offset == metadata["size"]:
            folder["done"].add(file_id)
            target = folder["staging"] / metadata["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(part_path.replace, target)

        return web.json_response(
            {
                "folder_id": folder_id,
                "file_id": file_id,
                "offset": actual_offset,
                "complete": actual_offset == metadata["size"],
            }
        )

    async def folder_complete(self, request: web.Request) -> web.Response:
        """Atomically promote a fully received staging directory.

        Only when every manifest entry has arrived is the staging directory
        renamed to its final, collision-free name. A partial folder is left in
        place so the sender can retry and resume.
        """
        self.authenticate(request)
        payload = await request.json()
        folder_id = str(payload.get("folder_id") or "")
        folder = self.folders.get(folder_id)
        if not folder:
            raise web.HTTPNotFound(text="Folder was not initialized.")
        missing = len(folder["files"]) - len(folder["done"])
        if missing:
            raise web.HTTPConflict(text=f"{missing} file(s) not received yet.")

        destination = unique_destination(
            self.config.incoming_directory,
            folder["name"],
        )
        await asyncio.to_thread(folder["staging"].replace, destination)
        total = sum(metadata["size"] for metadata in folder["files"].values())
        self.event_callback(
            FolderReceived(
                peer_id=folder["peer_id"],
                peer_name=folder["peer_name"],
                path=destination,
                size=total,
                transfer_id=folder_id,
            )
        )
        del self.folders[folder_id]
        return web.json_response(
            {
                "folder_id": folder_id,
                "name": folder["name"],
                "path": str(destination),
            }
        )
