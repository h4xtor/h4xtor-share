from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import aiohttp

from h4xtor_share.config import Config
from h4xtor_share.models import DESKTOP_CAPABILITIES, Peer, TransferProgress
from h4xtor_share.pairing import PairingInvite

CHUNK_SIZE = 1024 * 1024


async def _raise_for_status(response: aiohttp.ClientResponse) -> None:
    """Like ``raise_for_status`` but keeps the peer's human-readable reason."""
    if response.status < 400:
        return
    try:
        detail = (await response.text()).strip()
    except Exception:  # noqa: BLE001
        detail = ""
    raise RuntimeError(detail[:300] or f"HTTP {response.status} {response.reason}")


class PeerClient:
    def __init__(
        self,
        config: Config,
        fingerprint: str | None = None,
        capabilities: tuple[str, ...] = DESKTOP_CAPABILITIES,
    ) -> None:
        self.config = config
        #: This device's own certificate fingerprint. When known, pairing is
        #: made mutual: the initiator hands the receiver a token for the
        #: reverse direction so one pairing lets both sides send.
        self.fingerprint = fingerprint
        self.capabilities = capabilities
        self._resumable: dict[tuple[str, str], str] = {}

    @staticmethod
    def pairing_ssl(fingerprint: str | None = None) -> bool | aiohttp.Fingerprint:
        """TLS policy for unauthenticated calls.

        When the peer's fingerprint is already known (mDNS, UDP or a QR code)
        the connection is pinned to it; otherwise only encryption is used and
        the six-digit code authenticates the pairing.
        """
        if fingerprint and len(fingerprint) == 64:
            try:
                return PeerClient.pinned_ssl(fingerprint)
            except RuntimeError:
                return False
        return False

    def _reverse_credentials(self, peer_id: str, peer_name: str) -> dict[str, Any] | None:
        if not self.fingerprint:
            return None
        token = secrets.token_urlsafe(48)
        self.config.trust_inbound_peer(peer_id, token, peer_name)
        return {
            "token": token,
            "fingerprint": self.fingerprint,
            "port": self.config.port,
            "platform": self.config.platform_name,
            "capabilities": list(self.capabilities),
        }

    @staticmethod
    def pinned_ssl(fingerprint: str) -> aiohttp.Fingerprint:
        try:
            value = bytes.fromhex(fingerprint)
        except ValueError as error:
            raise RuntimeError("Peer certificate fingerprint is invalid.") from error
        if len(value) != 32:
            raise RuntimeError("Peer certificate fingerprint has the wrong length.")
        return aiohttp.Fingerprint(value)

    async def get_info(
        self,
        address: str,
        port: int,
        *,
        timeout_seconds: float = 8,
        expected_fingerprint: str | None = None,
    ) -> Peer:
        endpoint = f"https://{address}:{port}"
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(
            f"{endpoint}/api/v1/info",
            ssl=self.pairing_ssl(expected_fingerprint),
        ) as response:
            await _raise_for_status(response)
            payload = await response.json()
        return Peer(
            device_id=str(payload["device_id"]),
            name=str(payload["name"]),
            address=address,
            port=int(payload["port"]),
            fingerprint=str(payload["fingerprint"]),
            platform=str(payload.get("platform") or "unknown"),
            transport="lan",
            capabilities=tuple(
                str(capability) for capability in (payload.get("capabilities") or [])
            ),
        )

    async def ping(self, peer: Peer, *, timeout_seconds: float = 2) -> float:
        """Return the round-trip time in milliseconds for *peer*.

        Raises on any failure so the caller can mark the peer offline.
        """
        started = asyncio.get_running_loop().time()
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(
            f"{peer.endpoint}/api/v1/ping",
            ssl=self.pairing_ssl(),
        ) as response:
            await _raise_for_status(response)
            payload = await response.json(content_type=None)
        # An address can be reused by another device (or a reinstalled app with a
        # new id). Only count the peer as online when *it* answers.
        answered = str((payload or {}).get("device_id") or "")
        if answered and answered != peer.device_id:
            raise RuntimeError("A different device answered on this address.")
        return (asyncio.get_running_loop().time() - started) * 1000.0

    async def request_pairing(self, peer: Peer) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
            f"{peer.endpoint}/api/v1/pair/request",
            json={
                "device_id": self.config.device_id,
                "name": self.config.device_name,
            },
            ssl=self.pairing_ssl(peer.fingerprint),
        ) as response:
            await _raise_for_status(response)
            return await response.json()

    async def confirm_pairing(
        self,
        peer: Peer,
        pairing_id: str,
        code: str,
    ) -> None:
        timeout = aiohttp.ClientTimeout(total=10)
        body: dict[str, Any] = {"pairing_id": pairing_id, "code": code}
        reverse = self._reverse_credentials(peer.device_id, peer.name)
        if reverse is not None:
            body["reverse"] = reverse
        async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
            f"{peer.endpoint}/api/v1/pair/confirm",
            json=body,
            ssl=self.pairing_ssl(peer.fingerprint),
        ) as response:
            await _raise_for_status(response)
            payload = await response.json()
        self._store_pairing(peer, payload)

    def _store_pairing(self, peer: Peer, payload: dict[str, Any]) -> None:
        returned_fingerprint = str(payload["fingerprint"])
        if returned_fingerprint != peer.fingerprint:
            raise RuntimeError("Peer certificate changed during pairing.")
        self.config.trust_outbound_peer(
            peer.device_id,
            str(payload["token"]),
            returned_fingerprint,
            str(payload["name"]),
        )
        self.config.remember_peer(peer)

    async def pair_with_qr(self, invite: PairingInvite) -> Peer:
        """Pair using a scanned QR invite: find the peer, pin it, pair both ways."""
        last_error: Exception | None = None
        for address in invite.addresses:
            try:
                peer = await self.get_info(
                    address,
                    invite.port,
                    timeout_seconds=4,
                    expected_fingerprint=invite.fingerprint,
                )
            except Exception as error:  # noqa: BLE001 - try every advertised address
                last_error = error
                continue
            if peer.device_id != invite.device_id:
                last_error = RuntimeError("QR code belongs to a different device.")
                continue
            body: dict[str, Any] = {
                "secret": invite.secret,
                "device_id": self.config.device_id,
                "name": self.config.device_name,
                "reverse": self._reverse_credentials(peer.device_id, peer.name) or {},
            }
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
                f"{peer.endpoint}/api/v1/pair/qr",
                json=body,
                ssl=self.pinned_ssl(invite.fingerprint),
            ) as response:
                await _raise_for_status(response)
                payload = await response.json()
            self._store_pairing(peer, payload)
            return peer
        raise RuntimeError(f"Could not reach the device from the QR code: {last_error}")

    async def _authed_post(
        self, peer: Peer, path: str, body: dict[str, Any], timeout_seconds: float = 15
    ) -> dict[str, Any]:
        headers, ssl_value = self.auth(peer)
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
            f"{peer.endpoint}{path}",
            json=body,
            headers=headers,
            ssl=ssl_value,
        ) as response:
            await _raise_for_status(response)
            return await response.json()

    async def send_link(self, peer: Peer, url: str) -> None:
        """Push a URL that the receiver opens in its browser."""
        if not peer.supports("links"):
            await self.send_clipboard(peer, url)
            return
        await self._authed_post(peer, "/api/v1/link", {"url": url})

    async def send_wifi_direct_offer(
        self, peer: Peer, ssid: str, passphrase: str, owner_address: str, port: int
    ) -> None:
        await self._authed_post(
            peer,
            "/api/v1/wifi-direct/offer",
            {
                "ssid": ssid,
                "passphrase": passphrase,
                "owner_address": owner_address,
                "port": port,
            },
        )

    async def unpair(self, peer: Peer) -> None:
        """Forget *peer* locally and, best effort, ask it to forget us too."""
        try:
            if peer.supports("unpair") and self.config.is_trusted(peer.device_id):
                await self._authed_post(peer, "/api/v1/unpair", {}, timeout_seconds=4)
        except Exception:  # noqa: BLE001 - the local forget must always happen
            pass
        finally:
            self.config.forget_peer(peer.device_id)

    def auth(self, peer: Peer) -> tuple[dict[str, str], aiohttp.Fingerprint]:
        credentials = self.config.outbound_credentials(peer.device_id)
        if not credentials:
            raise RuntimeError("Pair with this device before sending data.")
        token, fingerprint = credentials
        return (
            {
                "Authorization": f"Bearer {token}",
                "X-H4xtor-Device": self.config.device_id,
            },
            self.pinned_ssl(fingerprint),
        )

    async def send_clipboard(self, peer: Peer, text: str) -> None:
        headers, ssl_value = self.auth(peer)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
            f"{peer.endpoint}/api/v1/clipboard",
            json={"text": text},
            headers=headers,
            ssl=ssl_value,
        ) as response:
            await _raise_for_status(response)

    async def send_file(
        self,
        peer: Peer,
        path: Path,
        progress_callback: Callable[[TransferProgress], None],
    ) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)
        # Reuse the transfer id of an interrupted attempt for this peer+file so
        # the receiver resumes from the bytes it already holds instead of
        # re-streaming them. Completed transfers are removed from the map.
        key = (peer.device_id, str(path.resolve()))
        transfer_id = self._resumable.pop(key, None) or uuid.uuid4().hex
        total = path.stat().st_size
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=60)

        try:
            headers, ssl_value = self.auth(peer)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{peer.endpoint}/api/v1/files/init",
                    json={
                        "transfer_id": transfer_id,
                        "name": path.name,
                        "size": total,
                    },
                    headers=headers,
                    ssl=ssl_value,
                ) as response:
                    await _raise_for_status(response)
                    metadata = await response.json()
                offset = int(metadata["offset"])
                progress_callback(
                    TransferProgress(
                        transfer_id=transfer_id,
                        file_name=path.name,
                        sent=offset,
                        total=total,
                        direction="send",
                    )
                )

                async def chunks() -> AsyncIterator[bytes]:
                    sent = offset
                    with path.open("rb") as source:
                        source.seek(offset)
                        while True:
                            chunk = await asyncio.to_thread(source.read, CHUNK_SIZE)
                            if not chunk:
                                break
                            sent += len(chunk)
                            progress_callback(
                                TransferProgress(
                                    transfer_id=transfer_id,
                                    file_name=path.name,
                                    sent=sent,
                                    total=total,
                                    direction="send",
                                )
                            )
                            yield chunk

                upload_headers = dict(headers)
                upload_headers["X-H4xtor-Offset"] = str(offset)
                async with session.put(
                    f"{peer.endpoint}/api/v1/files/{transfer_id}",
                    data=chunks(),
                    headers=upload_headers,
                    ssl=ssl_value,
                ) as response:
                    await _raise_for_status(response)
                    result = await response.json()
                if not result.get("complete"):
                    raise RuntimeError(
                        "Transfer stopped before the complete file arrived."
                    )
                progress_callback(
                    TransferProgress(
                        transfer_id=transfer_id,
                        file_name=path.name,
                        sent=total,
                        total=total,
                        direction="send",
                    )
                )
        except BaseException:
            # Also on cancellation: a later retry resumes from the same bytes.
            self._resumable[key] = transfer_id
            raise

    async def send_folder(
        self,
        peer: Peer,
        path: Path,
        progress_callback: Callable[[TransferProgress], None],
    ) -> None:
        """Transfer *path* and its entire subtree to *peer*.

        A manifest of every file (relative path, size, per-file transfer id) is
        negotiated with ``/api/v1/folders/init``. Files are streamed in one
        bounded-concurrency wave into the receiver's staging directory and the
        whole folder is atomically promoted by ``/api/v1/folders/complete``.
        """
        if not path.is_dir():
            raise NotADirectoryError(path)
        files = sorted(child for child in path.rglob("*") if child.is_file())
        if not files:
            raise ValueError("The folder is empty.")
        folder_id = uuid.uuid4().hex
        entries = [
            {
                "id": uuid.uuid4().hex,
                "path": child.relative_to(path).as_posix(),
                "size": child.stat().st_size,
            }
            for child in files
        ]
        total = sum(entry["size"] for entry in entries)
        headers, ssl_value = self.auth(peer)
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=60)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{peer.endpoint}/api/v1/folders/init",
                json={
                    "folder_id": folder_id,
                    "name": path.name,
                    "entries": entries,
                },
                headers=headers,
                ssl=ssl_value,
            ) as response:
                await _raise_for_status(response)
                initialized = await response.json()
            offsets = {
                str(entry["id"]): int(entry["offset"])
                for entry in initialized.get("entries", [])
            }
            semaphore = asyncio.Semaphore(4)
            # Aggregate per-file progress into one folder-level progress stream.
            progress_by_file: dict[str, int] = dict.fromkeys(
                (str(entry["id"]) for entry in entries), 0
            )
            progress_by_file.update(offsets)

            def file_progress(event: TransferProgress) -> None:
                progress_by_file[event.transfer_id] = event.sent
                progress_callback(
                    TransferProgress(
                        transfer_id=folder_id,
                        file_name=path.name,
                        sent=sum(progress_by_file.values()),
                        total=total,
                        direction="send",
                    )
                )

            async def send_entry(entry: dict[str, Any], source: Path) -> None:
                async with semaphore:
                    await self._upload_folder_entry(
                        session,
                        peer,
                        folder_id,
                        entry,
                        source,
                        offsets.get(str(entry["id"]), 0),
                        headers,
                        ssl_value,
                        file_progress,
                    )

            await asyncio.gather(
                *(send_entry(entry, source) for entry, source in zip(entries, files, strict=True))
            )

            async with session.post(
                f"{peer.endpoint}/api/v1/folders/complete",
                json={"folder_id": folder_id},
                headers=headers,
                ssl=ssl_value,
            ) as response:
                await _raise_for_status(response)
        progress_callback(
            TransferProgress(
                transfer_id=folder_id,
                file_name=path.name,
                sent=total,
                total=total,
                direction="send",
            )
        )

    async def _upload_folder_entry(
        self,
        session: aiohttp.ClientSession,
        peer: Peer,
        folder_id: str,
        entry: dict[str, Any],
        source: Path,
        offset: int,
        headers: dict[str, str],
        ssl_value: aiohttp.Fingerprint,
        progress_callback: Callable[[TransferProgress], None],
    ) -> None:
        file_id = str(entry["id"])
        total = int(entry["size"])
        display = source.name
        if offset:
            progress_callback(
                TransferProgress(
                    transfer_id=file_id,
                    file_name=display,
                    sent=offset,
                    total=total,
                    direction="send",
                )
            )

        async def chunks() -> AsyncIterator[bytes]:
            sent = offset
            with source.open("rb") as input_stream:
                input_stream.seek(offset)
                while True:
                    chunk = await asyncio.to_thread(input_stream.read, CHUNK_SIZE)
                    if not chunk:
                        break
                    sent += len(chunk)
                    progress_callback(
                        TransferProgress(
                            transfer_id=file_id,
                            file_name=display,
                            sent=sent,
                            total=total,
                            direction="send",
                        )
                    )
                    yield chunk

        upload_headers = dict(headers)
        upload_headers["X-H4xtor-Offset"] = str(offset)
        async with session.put(
            f"{peer.endpoint}/api/v1/folders/{folder_id}/{file_id}",
            data=chunks(),
            headers=upload_headers,
            ssl=ssl_value,
        ) as response:
            await _raise_for_status(response)
            result = await response.json()
        if not result.get("complete"):
            raise RuntimeError(
                "Folder transfer stopped before the complete file arrived."
            )
