"""Loopback API for the h4xtor share Chrome extension.

The extension talks to the desktop app on ``127.0.0.1`` only. Security model:

* the server binds to the loopback interface, never the LAN;
* every request from a normal web page is refused: only ``chrome-extension://``
  (or other ``*-extension://``) origins and origin-less local tools are served,
  so a website cannot drive the app (no CSRF);
* the extension must be approved once in the desktop app ("Tillad"); it then
  receives a random token that every later call must present.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from h4xtor_share import __version__
from h4xtor_share.config import Config

LOCAL_API_PORT_OFFSET = 2
EXTENSION_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://", "edge-extension://")

DevicesProvider = Callable[[], list[dict[str, Any]]]
Sender = Callable[[str, str, str], Awaitable[None]]
Approver = Callable[[str, str], Awaitable[bool]]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LocalApi:
    def __init__(
        self,
        config: Config,
        port: int,
        devices: DevicesProvider,
        sender: Sender,
        approver: Approver,
        host: str = "127.0.0.1",
    ) -> None:
        self.config = config
        self.port = port
        self.host = host
        self.devices = devices
        self.sender = sender
        self.approver = approver
        self.runner: web.AppRunner | None = None
        self.app = web.Application(middlewares=[self._guard], client_max_size=1024 * 1024)
        self.app.add_routes(
            [
                web.get("/v1/status", self.status),
                web.post("/v1/connect", self.connect),
                web.get("/v1/devices", self.list_devices),
                web.post("/v1/send", self.send),
                web.post("/v1/disconnect", self.disconnect),
            ]
        )

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host=self.host, port=self.port)
        await site.start()

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
        self.runner = None

    # -- security ------------------------------------------------------------
    @staticmethod
    def _origin_allowed(origin: str) -> bool:
        if not origin:
            return True  # curl / local tools: still need a token for anything useful
        return origin.startswith(EXTENSION_ORIGIN_PREFIXES)

    @web.middleware
    async def _guard(self, request: web.Request, handler: Any) -> web.StreamResponse:
        origin = request.headers.get("Origin", "")
        if not self._origin_allowed(origin):
            raise web.HTTPForbidden(text="Only the h4xtor share browser extension may connect.")
        if request.method == "OPTIONS":
            response: web.StreamResponse = web.Response(status=204)
        else:
            response = await handler(request)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    def _clients(self) -> dict[str, Any]:
        clients = self.config.data.setdefault("local_clients", {})
        return clients if isinstance(clients, dict) else {}

    def _authorised(self, request: web.Request) -> bool:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        digest = _hash(header.removeprefix("Bearer ").strip())
        return any(secrets.compare_digest(digest, known) for known in self._clients())

    def _require(self, request: web.Request) -> None:
        if not self._authorised(request):
            raise web.HTTPUnauthorized(text="Connect the extension to h4xtor share first.")

    # -- endpoints -----------------------------------------------------------
    async def status(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "app": "h4xtor-share",
                "version": __version__,
                "name": self.config.device_name,
                "authorised": self._authorised(request),
            }
        )

    async def connect(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        name = str(payload.get("name") or "Chrome")[:60]
        origin = request.headers.get("Origin", "local tool")
        if not await self.approver(name, origin):
            raise web.HTTPForbidden(text="The connection was declined in h4xtor share.")
        token = secrets.token_urlsafe(32)
        self._clients()[_hash(token)] = {"name": name, "origin": origin}
        self.config.save()
        return web.json_response({"token": token, "name": self.config.device_name})

    async def disconnect(self, request: web.Request) -> web.Response:
        self._require(request)
        digest = _hash(request.headers["Authorization"].removeprefix("Bearer ").strip())
        self._clients().pop(digest, None)
        self.config.save()
        return web.json_response({"ok": True})

    async def list_devices(self, request: web.Request) -> web.Response:
        self._require(request)
        return web.json_response({"devices": self.devices()})

    async def send(self, request: web.Request) -> web.Response:
        self._require(request)
        try:
            payload = await request.json()
        except ValueError as error:
            raise web.HTTPBadRequest(text="Invalid JSON.") from error
        device_id = str(payload.get("device_id") or "")
        kind = str(payload.get("kind") or "")
        value = str(payload.get("value") or "").strip()
        if kind not in {"link", "text", "file-url"} or not value:
            raise web.HTTPBadRequest(text="Nothing to send.")
        if len(value) > 100_000:
            raise web.HTTPBadRequest(text="Too much text.")
        known = {device["id"] for device in self.devices()}
        if device_id not in known:
            raise web.HTTPNotFound(text="Unknown or unpaired device.")
        try:
            await self.sender(device_id, kind, value)
        except Exception as error:  # noqa: BLE001 - report the reason to the extension
            raise web.HTTPBadGateway(text=str(error) or "Sending failed.") from error
        return web.json_response({"ok": True})
