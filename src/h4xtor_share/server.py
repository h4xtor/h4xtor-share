from __future__ import annotations

import asyncio
import re
import secrets
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiofiles
from aiohttp import web

from h4xtor_share.config import Config
from h4xtor_share.models import (
    ClipboardReceived,
    FileReceived,
    PairingPrompt,
    TransferProgress,
)

PAIRING_TTL_SECONDS = 120
CHUNK_SIZE = 1024 * 1024
TRANSFER_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def safe_file_name(value: str) -> str:
    name = Path(value.replace("\\", "/")).name.strip().replace("\x00", "")
    if name in {"", ".", ".."}:
        raise ValueError("Invalid file name.")
    return name[:240]


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
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.app = web.Application(client_max_size=0)
        self.app.add_routes(
            [
                web.get("/api/v1/info", self.info),
                web.post("/api/v1/pair/request", self.pair_request),
                web.post("/api/v1/pair/confirm", self.pair_confirm),
                web.post("/api/v1/clipboard", self.clipboard),
                web.post("/api/v1/files/init", self.file_init),
                web.put("/api/v1/files/{transfer_id}", self.file_upload),
            ]
        )

    async def start(self) -> None:
        self.config.incoming_directory.mkdir(parents=True, exist_ok=True)
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(
            self.runner,
            host="0.0.0.0",
            port=self.config.port,
            ssl_context=self.ssl_context,
        )
        await self.site.start()

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
                "capabilities": ["clipboard", "files", "resume"],
            }
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

        token = secrets.token_urlsafe(48)
        self.config.trust_inbound_peer(
            pending["peer_id"],
            token,
            pending["peer_name"],
        )
        return web.json_response(
            {
                "token": token,
                "device_id": self.config.device_id,
                "name": self.config.device_name,
                "fingerprint": self.fingerprint,
            }
        )

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
        _peer_id, peer_name = self.authenticate(request)
        payload = await request.json()
        text = payload.get("text")
        if not isinstance(text, str):
            raise web.HTTPBadRequest(text="Clipboard payload must contain text.")
        self.event_callback(ClipboardReceived(peer_name=peer_name, text=text))
        return web.json_response({"accepted": True, "characters": len(text)})

    async def file_init(self, request: web.Request) -> web.Response:
        _peer_id, peer_name = self.authenticate(request)
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
                    peer_name=transfer["peer_name"],
                    path=destination,
                    size=transfer["size"],
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
