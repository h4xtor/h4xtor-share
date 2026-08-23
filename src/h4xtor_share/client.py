from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import aiohttp

from h4xtor_share.config import Config
from h4xtor_share.models import Peer, TransferProgress

CHUNK_SIZE = 1024 * 1024


class PeerClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._resumable: dict[tuple[str, str], str] = {}

    @staticmethod
    def pairing_ssl() -> bool:
        return False

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
    ) -> Peer:
        endpoint = f"https://{address}:{port}"
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(
            f"{endpoint}/api/v1/info",
            ssl=self.pairing_ssl(),
        ) as response:
            response.raise_for_status()
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
            response.raise_for_status()
        return (asyncio.get_running_loop().time() - started) * 1000.0

    async def request_pairing(self, peer: Peer) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
            f"{peer.endpoint}/api/v1/pair/request",
            json={
                "device_id": self.config.device_id,
                "name": self.config.device_name,
            },
            ssl=self.pairing_ssl(),
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def confirm_pairing(
        self,
        peer: Peer,
        pairing_id: str,
        code: str,
    ) -> None:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
            f"{peer.endpoint}/api/v1/pair/confirm",
            json={
                "pairing_id": pairing_id,
                "code": code,
            },
            ssl=self.pairing_ssl(),
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        returned_fingerprint = str(payload["fingerprint"])
        if returned_fingerprint != peer.fingerprint:
            raise RuntimeError("Peer certificate changed during pairing.")
        self.config.trust_outbound_peer(
            peer.device_id,
            str(payload["token"]),
            returned_fingerprint,
            str(payload["name"]),
        )

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
            response.raise_for_status()

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
                    response.raise_for_status()
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
                    response.raise_for_status()
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
        except Exception:
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
                response.raise_for_status()
                initialized = await response.json()
            offsets = {
                str(entry["id"]): int(entry["offset"])
                for entry in initialized.get("entries", [])
            }
            semaphore = asyncio.Semaphore(4)

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
                        progress_callback,
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
                response.raise_for_status()
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
            response.raise_for_status()
            result = await response.json()
        if not result.get("complete"):
            raise RuntimeError(
                "Folder transfer stopped before the complete file arrived."
            )
