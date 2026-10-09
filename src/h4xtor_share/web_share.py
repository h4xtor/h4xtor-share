"""Share with an iPhone (or any phone) from the browser – no app needed.

The PC serves a small web page on the LAN. A phone opens it by scanning a QR
code that carries a long random key; every API call must present that key.

Security model and its honest limits:

* off until the user switches it on in the desktop app;
* the key (32 random bytes) is the only way in; "Nyt link" replaces it, which
  locks out every phone that had the old one;
* plain HTTP on the local network: a browser would warn about the app's
  self-signed certificate, so this path is not TLS-encrypted like app-to-app.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiofiles
from aiohttp import web

from h4xtor_share import __version__
from h4xtor_share.config import Config
from h4xtor_share.models import ClipboardReceived, FileReceived, LinkReceived, TransferProgress
from h4xtor_share.server import CHUNK_SIZE, is_safe_url, safe_file_name, unique_destination
from h4xtor_share.web_page import PAGE

WEB_PORT_OFFSET = 4
WEB_PEER_ID = "web"
MAX_TEXT = 100_000
MAX_OUTBOX = 50


def device_label(user_agent: str) -> str:
    for marker, label in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android")):
        if marker in user_agent:
            return label
    return "Browser"


@dataclass
class OutboxItem:
    item_id: str
    kind: str  # file | text
    name: str
    size: int = 0
    path: str = ""
    text: str = ""
    created: float = 0.0
    downloads: int = 0

    def public(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.item_id,
            "kind": self.kind,
            "name": self.name,
            "size": self.size,
            "created": int(self.created * 1000),
            "downloads": self.downloads,
        }
        if self.kind == "text":
            data["text"] = self.text
        return data


class WebShare:
    def __init__(
        self,
        config: Config,
        port: int,
        event_callback: Callable[[object], None],
        clipboard_reader: Callable[[], Awaitable[str]],
        host: str = "0.0.0.0",
    ) -> None:
        self.config = config
        self.port = port
        self.host = host
        self.event_callback = event_callback
        self.clipboard_reader = clipboard_reader
        self.outbox: list[OutboxItem] = []
        self.runner: web.AppRunner | None = None
        self.app = web.Application(client_max_size=1024 * 1024)
        self.app.add_routes(
            [
                web.get("/", self.page),
                web.get("/icon.png", self.icon),
                web.get("/api/state", self.state),
                web.post("/api/text", self.text),
                web.post("/api/upload", self.upload),
                web.get("/api/files/{item_id}", self.download),
                web.get("/api/clipboard", self.clipboard),
            ]
        )

    # -- settings ------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.config.data.get("web_enabled", False))

    @property
    def token(self) -> str:
        token = str(self.config.data.get("web_token") or "")
        if not token:
            token = self.new_token()
        return token

    def new_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self.config.data["web_token"] = token
        self.config.save()
        return token

    def url(self, address: str) -> str:
        return f"http://{address}:{self.port}/?k={self.token}"

    # -- lifecycle -----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.runner is not None

    async def start(self) -> None:
        if self.runner is not None:
            return
        runner = web.AppRunner(self.app, access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, host=self.host, port=self.port).start()
        except OSError:
            await runner.cleanup()
            raise
        self.runner = runner

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
        self.runner = None

    # -- outbox (PC → phone) ---------------------------------------------------
    def add_file(self, path: Path) -> OutboxItem:
        item = OutboxItem(
            uuid.uuid4().hex,
            "file",
            path.name,
            size=path.stat().st_size,
            path=str(path),
            created=time.time(),
        )
        return self._add(item)

    def add_text(self, text: str) -> OutboxItem:
        label = text.strip().splitlines()[0][:80] if text.strip() else "Tekst"
        item = OutboxItem(
            uuid.uuid4().hex, "text", label, text=text[:MAX_TEXT], created=time.time()
        )
        return self._add(item)

    def _add(self, item: OutboxItem) -> OutboxItem:
        self.outbox.insert(0, item)
        del self.outbox[MAX_OUTBOX:]
        return item

    def remove(self, item_id: str) -> None:
        self.outbox = [item for item in self.outbox if item.item_id != item_id]

    # -- security --------------------------------------------------------------
    def _require(self, request: web.Request) -> None:
        given = request.headers.get("X-H4xtor-Key") or request.query.get("k", "")
        if not self.enabled or not secrets.compare_digest(given.encode(), self.token.encode()):
            raise web.HTTPUnauthorized(text="Scan QR-koden på PC'en igen.")

    @staticmethod
    def _peer_name(request: web.Request) -> str:
        return device_label(request.headers.get("User-Agent", ""))

    # -- endpoints ---------------------------------------------------------------
    async def page(self, _request: web.Request) -> web.Response:
        # The page holds no secrets; it reads the key from its own URL.
        return web.Response(
            text=PAGE,
            content_type="text/html",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def icon(self, _request: web.Request) -> web.Response:
        data = (
            resources.files("h4xtor_share") / "chrome_extension" / "icons" / "icon128.png"
        ).read_bytes()
        return web.Response(body=data, content_type="image/png")

    async def state(self, request: web.Request) -> web.Response:
        self._require(request)
        return web.json_response(
            {
                "pc": self.config.device_name,
                "version": __version__,
                "outbox": [item.public() for item in self.outbox],
            }
        )

    async def text(self, request: web.Request) -> web.Response:
        self._require(request)
        try:
            payload = await request.json()
        except ValueError as error:
            raise web.HTTPBadRequest(text="Invalid JSON.") from error
        value = str(payload.get("text") or "").strip()
        if not value or len(value) > MAX_TEXT:
            raise web.HTTPBadRequest(text="Ingen tekst.")
        name = self._peer_name(request)
        if is_safe_url(value):
            self.event_callback(LinkReceived(WEB_PEER_ID, name, value))
            return web.json_response({"ok": True, "kind": "link"})
        self.event_callback(ClipboardReceived(WEB_PEER_ID, name, value))
        return web.json_response({"ok": True, "kind": "text"})

    async def upload(self, request: web.Request) -> web.Response:
        self._require(request)
        try:
            file_name = safe_file_name(request.query.get("name", ""))
            total = int(request.query.get("size", "-1"))
        except ValueError as error:
            raise web.HTTPBadRequest(text="Ugyldigt filnavn eller størrelse.") from error
        if total < 0:
            raise web.HTTPBadRequest(text="Ugyldig størrelse.")
        peer_name = self._peer_name(request)
        transfer_id = uuid.uuid4().hex
        incoming = self.config.incoming_directory
        incoming.mkdir(parents=True, exist_ok=True)
        part = incoming / f".h4xtor-{transfer_id}.part"
        received = 0
        last_report = 0.0
        try:
            async with aiofiles.open(part, "wb") as output:
                async for chunk in request.content.iter_chunked(CHUNK_SIZE):
                    received += len(chunk)
                    if received > total:
                        raise web.HTTPBadRequest(text="Filen er større end oplyst.")
                    await output.write(chunk)
                    now = time.monotonic()
                    if now - last_report >= 0.2:
                        last_report = now
                        self.event_callback(
                            TransferProgress(
                                transfer_id, file_name, received, total, "receive", peer_name
                            )
                        )
            if received != total:
                raise web.HTTPBadRequest(text="Overførslen blev afbrudt.")
            destination = unique_destination(incoming, file_name)
            await asyncio.to_thread(part.replace, destination)
        finally:
            with contextlib.suppress(OSError):
                part.unlink(missing_ok=True)
        self.event_callback(
            FileReceived(WEB_PEER_ID, peer_name, destination, total, transfer_id=transfer_id)
        )
        return web.json_response({"ok": True, "name": destination.name})

    async def download(self, request: web.Request) -> web.StreamResponse:
        self._require(request)
        item = next(
            (item for item in self.outbox if item.item_id == request.match_info["item_id"]),
            None,
        )
        if item is None or item.kind != "file" or not Path(item.path).is_file():
            raise web.HTTPNotFound(text="Filen findes ikke længere på PC'en.")
        disposition = "inline" if request.query.get("inline") else "attachment"
        response = web.FileResponse(
            item.path,
            headers={
                "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(item.name)}",
                "Cache-Control": "no-store",
            },
        )
        if request.query.get("preview"):
            return response  # the page's own thumbnail, not a delivery
        item.downloads += 1
        self.event_callback(
            TransferProgress(
                item.item_id, item.name, item.size, item.size, "send", self._peer_name(request)
            )
        )
        return response

    async def clipboard(self, request: web.Request) -> web.Response:
        self._require(request)
        try:
            text = await asyncio.wait_for(self.clipboard_reader(), timeout=3)
        except Exception:  # noqa: BLE001 - an empty clipboard is fine
            text = ""
        return web.json_response({"text": text})
