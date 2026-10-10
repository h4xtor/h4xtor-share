from __future__ import annotations

import asyncio
import base64
import socket
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest
from aiohttp import web

from h4xtor_share import gdrive as gdrive_mod
from h4xtor_share.client import PeerClient
from h4xtor_share.config import Config
from h4xtor_share.crypto import certificate_fingerprint, ensure_certificate, server_ssl_context
from h4xtor_share.gdrive import GoogleDrive, GoogleDriveError, pkce_challenge
from h4xtor_share.models import (
    DESKTOP_CAPABILITIES,
    NotificationReceived,
    NotificationRemoved,
    Peer,
    SmsReceived,
)
from h4xtor_share.server import ShareServer

PHONE_CAPS = (
    "notifications",
    "sms",
    "screenshot-request",
    "find-phone",
    "remote-control",
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# -- desktop server endpoints -------------------------------------------------
@pytest.fixture
async def desktop(tmp_path: Path):
    config = Config(tmp_path / "pc" / "config.json")
    config.data["port"] = free_port()
    config.trust_inbound_peer("p" * 32, "secret-token", "Pixel")
    certificate, key, fingerprint = ensure_certificate(config.path.parent, "PC")
    events: list[object] = []
    server = ShareServer(
        config, server_ssl_context(certificate, key), fingerprint, events.append, host="127.0.0.1"
    )
    await server.start()
    yield config, events
    await server.stop()


async def post(config: Config, path: str, body, *, auth: bool = True, raw: str | None = None):
    headers = {"Authorization": "Bearer secret-token", "X-H4xtor-Device": "p" * 32}
    async with aiohttp.ClientSession() as session:
        kwargs = {"data": raw} if raw is not None else {"json": body}
        async with session.post(
            f"https://127.0.0.1:{config.port}{path}",
            headers=headers if auth else {},
            ssl=False,
            **kwargs,
        ) as response:
            return response.status, await response.text()


def test_capabilities_advertised() -> None:
    assert "notifications" in DESKTOP_CAPABILITIES
    assert "sms" in DESKTOP_CAPABILITIES


async def test_notification_posted_clips_and_decodes_icon(desktop) -> None:
    config, events = desktop
    icon = base64.b64encode(b"\x89PNGdata").decode()
    status, _ = await post(
        config,
        "/api/v1/notification",
        {
            "event": "posted",
            "key": "k" * 600,
            "package": "com.whatsapp",
            "app": "WhatsApp",
            "title": "t" * 500,
            "text": "x" * 5000,
            "time": 1760090000000,
            "icon": icon,
            "can_reply": True,
            "can_dismiss": True,
        },
    )
    assert status == 200
    event = events[0]
    assert isinstance(event, NotificationReceived)
    assert event.peer_name == "Pixel"
    assert len(event.key) == 512
    assert len(event.title) == 200
    assert len(event.text) == 4000
    assert event.icon_png == b"\x89PNGdata"
    assert event.can_reply and event.can_dismiss
    assert event.time == 1760090000000


async def test_notification_invalid_or_huge_icon_dropped(desktop) -> None:
    config, events = desktop
    for icon in ("not base64!!", "A" * (64 * 1024 + 4)):
        status, _ = await post(
            config, "/api/v1/notification", {"event": "posted", "key": "k", "icon": icon}
        )
        assert status == 200
    assert [e.icon_png for e in events] == [b"", b""]


async def test_notification_removed_and_errors(desktop) -> None:
    config, events = desktop
    assert (await post(config, "/api/v1/notification", {"event": "removed", "key": "k1"}))[0] == 200
    assert isinstance(events[0], NotificationRemoved)
    assert events[0].key == "k1"
    assert (await post(config, "/api/v1/notification", {"event": "boom", "key": "k"}))[0] == 400
    assert (await post(config, "/api/v1/notification", {"event": "posted"}))[0] == 400
    assert (await post(config, "/api/v1/notification", None, raw="not json"))[0] == 400
    assert (await post(config, "/api/v1/notification", [1]))[0] == 400
    assert (await post(config, "/api/v1/notification", {"event": "removed"}, auth=False))[0] == 401
    assert len(events) == 1


async def test_sms_incoming(desktop) -> None:
    config, events = desktop
    status, _ = await post(
        config,
        "/api/v1/sms/incoming",
        {
            "thread_id": "12",
            "address": "+4512345678" + "0" * 100,
            "name": "n" * 200,
            "body": "b" * 5000,
            "time": 5,
        },
    )
    assert status == 200
    event = events[0]
    assert isinstance(event, SmsReceived)
    assert event.thread_id == "12"
    assert len(event.address) == 64
    assert len(event.name) == 80
    assert len(event.body) == 4000
    assert (await post(config, "/api/v1/sms/incoming", {"body": "x"}))[0] == 400
    assert (await post(config, "/api/v1/sms/incoming", None, raw="{"))[0] == 400
    assert (await post(config, "/api/v1/sms/incoming", {"address": "1"}, auth=False))[0] == 401


# -- client against a fake phone ---------------------------------------------
class FakePhone:
    def __init__(self, root: Path) -> None:
        self.calls: list[tuple[str, str, dict[str, str], object]] = []
        self.port = free_port()
        config = Config(root / "phone" / "config.json")
        certificate, key, self.fingerprint = ensure_certificate(config.path.parent, "Phone")
        self.ssl = server_ssl_context(certificate, key)
        self.runner: web.AppRunner | None = None

    async def handle(self, request: web.Request) -> web.Response:
        body: object = (
            await request.read() if request.method == "PUT" else await request.json()
        )
        self.calls.append((request.method, request.path, dict(request.headers), body))
        data = body if isinstance(body, dict) else {}
        replies = {
            "/api/v1/sms/threads": {"threads": [{"thread_id": "1"}]},
            "/api/v1/sms/messages": {"messages": [{"id": "9"}]},
            "/api/v1/find": {"ringing": data.get("action") == "start"},
            "/api/v1/remote/volume": {"level": data.get("level", 0)},
        }
        return web.json_response(replies.get(request.path, {"ok": True}))

    async def start(self) -> None:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", self.port, ssl_context=self.ssl).start()

    async def stop(self) -> None:
        assert self.runner
        await self.runner.cleanup()


@pytest.fixture
async def phone(tmp_path: Path):
    fake = FakePhone(tmp_path)
    await fake.start()
    config = Config(tmp_path / "pc" / "config.json")
    config.trust_outbound_peer("f" * 32, "phone-token", fake.fingerprint, "Phone")
    client = PeerClient(config)
    peer = Peer(
        "f" * 32, "Phone", "127.0.0.1", fake.port, fake.fingerprint, "android",
        capabilities=PHONE_CAPS,
    )
    yield fake, client, peer
    await fake.stop()


def last(fake: FakePhone):
    method, path, headers, body = fake.calls[-1]
    assert headers["Authorization"] == "Bearer phone-token"
    assert headers["X-H4xtor-Device"]
    return method, path, headers, body


async def test_client_phone_calls(phone) -> None:
    fake, client, peer = phone
    await client.notification_action(peer, "k", "reply", "hej")
    assert last(fake)[1:2] == ("/api/v1/notification/action",)
    assert last(fake)[3] == {"key": "k", "action": "reply", "text": "hej"}
    await client.notification_action(peer, "k", "dismiss")
    assert last(fake)[3] == {"key": "k", "action": "dismiss"}

    assert await client.sms_threads(peer, 5) == [{"thread_id": "1"}]
    assert last(fake)[3] == {"limit": 5}
    assert await client.sms_messages(peer, "1") == [{"id": "9"}]
    assert last(fake)[3] == {"thread_id": "1", "limit": 100}
    await client.send_sms(peer, "+45", "hej")
    assert last(fake)[3] == {"address": "+45", "text": "hej"}

    await client.request_screenshot(peer)
    assert last(fake)[1] == "/api/v1/screenshot"
    assert await client.find_phone(peer, True) is True
    assert await client.find_phone(peer, False) is False
    assert last(fake)[3] == {"action": "stop"}
    assert await client.set_volume(peer, 250) == 100
    assert last(fake)[3] == {"level": 100}
    assert await client.set_volume(peer, -3) == 0
    await client.speak(peer, "s" * 2000)
    assert last(fake)[3] == {"text": "s" * 1000}


async def test_client_wallpaper(phone, tmp_path: Path) -> None:
    fake, client, peer = phone
    image = tmp_path / "bg.png"
    image.write_bytes(b"png-bytes")
    await client.set_wallpaper(peer, image)
    method, path, headers, body = last(fake)
    assert (method, path, body) == ("PUT", "/api/v1/remote/wallpaper", b"png-bytes")
    assert headers["Content-Type"] == "image/png"

    huge = tmp_path / "huge.jpg"
    with huge.open("wb") as handle:
        handle.truncate(20 * 1024 * 1024 + 1)
    with pytest.raises(ValueError):
        await client.set_wallpaper(peer, huge)
    text = tmp_path / "a.txt"
    text.write_text("x")
    with pytest.raises(ValueError):
        await client.set_wallpaper(peer, text)


async def test_client_capability_guards(phone) -> None:
    _fake, client, peer = phone
    old = Peer(peer.device_id, "Old", peer.address, peer.port, peer.fingerprint, "android")
    for call in (
        client.notification_action(old, "k", "dismiss"),
        client.sms_threads(old),
        client.sms_messages(old, "1"),
        client.send_sms(old, "1", "x"),
        client.request_screenshot(old),
        client.find_phone(old, True),
        client.set_volume(old, 5),
        client.speak(old, "x"),
        client.set_wallpaper(old, Path("nope.png")),
    ):
        with pytest.raises(RuntimeError, match="Telefonen skal opdateres"):
            await call


async def test_push_helpers_reach_desktop(desktop, tmp_path: Path) -> None:
    config, events = desktop
    phone_config = Config(tmp_path / "emu" / "config.json")
    pinned = certificate_fingerprint(next(config.path.parent.glob("*.pem")))
    phone_config.trust_outbound_peer("d" * 32, "secret-token", pinned, "PC")
    phone_config.data["device_id"] = "p" * 32
    emulator = PeerClient(phone_config)
    pc = Peer("d" * 32, "PC", "127.0.0.1", config.port, pinned, "windows")
    await emulator.push_notification(pc, {"event": "posted", "key": "k", "title": "Hej"})
    await emulator.push_sms(pc, {"address": "+45", "body": "hej"})
    assert isinstance(events[0], NotificationReceived)
    assert isinstance(events[1], SmsReceived)


async def test_send_to_all_mixed() -> None:
    peers = [Peer(str(i), f"p{i}", "h", 1, "f", "x") for i in range(3)]

    async def work(peer: Peer) -> None:
        await asyncio.sleep(0)
        if peer.device_id == "1":
            raise RuntimeError("nede")

    outcomes = await PeerClient.send_to_all(peers, work)
    assert [p.device_id for p, _ in outcomes] == ["0", "1", "2"]
    assert outcomes[0][1] is None
    assert isinstance(outcomes[1][1], RuntimeError)
    assert outcomes[2][1] is None
    assert await PeerClient.send_to_all([], work) == []


async def test_send_to_all_reraises_cancel() -> None:
    async def work(_peer: Peer) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await PeerClient.send_to_all([Peer("0", "p", "h", 1, "f", "x")], work)


# -- Google Drive -----------------------------------------------------------------
def test_pkce_challenge_matches_rfc7636_example() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class FakeGoogle:
    def __init__(self) -> None:
        self.token_forms: list[dict[str, str]] = []
        self.revoked: list[str] = []
        self.runner: web.AppRunner | None = None
        self.base = ""

    async def token(self, request: web.Request) -> web.Response:
        form = dict(await request.post())
        self.token_forms.append(form)
        if form["grant_type"] == "authorization_code":
            return web.json_response({"access_token": "acc1", "refresh_token": "ref1"})
        assert form["refresh_token"] == "ref1"
        return web.json_response({"access_token": "acc2"})

    async def about(self, request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer acc1"
        return web.json_response({"user": {"emailAddress": "me@example.com"}})

    async def files(self, request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer acc2"
        assert "root" in request.query["q"]
        return web.json_response({"files": [{"name": "A"}, {"name": "B"}]})

    async def revoke(self, request: web.Request) -> web.Response:
        self.revoked.append((await request.post())["token"])
        return web.Response()

    async def start(self) -> None:
        app = web.Application()
        app.add_routes(
            [
                web.post("/token", self.token),
                web.get("/drive/v3/about", self.about),
                web.get("/drive/v3/files", self.files),
                web.post("/revoke", self.revoke),
            ]
        )
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.base = f"http://127.0.0.1:{self.runner.addresses[0][1]}"


@pytest.fixture
async def google(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("H4XTOR_GDRIVE_CLIENT_ID", raising=False)
    monkeypatch.delenv("H4XTOR_GDRIVE_CLIENT_SECRET", raising=False)
    fake = FakeGoogle()
    await fake.start()
    config = Config(tmp_path / "gd" / "config.json")
    config.data["gdrive_client_id"] = "cid"
    config.data["gdrive_client_secret"] = "csec"
    drive = GoogleDrive(config)
    drive.AUTH_URL = f"{fake.base}/auth"
    drive.TOKEN_URL = f"{fake.base}/token"
    drive.REVOKE_URL = f"{fake.base}/revoke"
    drive.API_BASE = fake.base
    yield fake, drive
    assert fake.runner
    await fake.runner.cleanup()


def browser(*, state: str | None = None, error: str | None = None, seen: list | None = None):
    """Return an open_url callback that plays the user's browser."""

    def open_url(url: str) -> None:
        params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        if seen is not None:
            seen.append(params)

        async def visit() -> None:
            query = {"state": state or params["state"]}
            query.update({"error": error} if error else {"code": "the-code"})
            async with aiohttp.ClientSession() as session:
                await session.get(params["redirect_uri"], params=query)

        asyncio.get_running_loop().create_task(visit())

    return open_url


async def test_gdrive_full_flow(google) -> None:
    fake, drive = google
    seen: list[dict[str, str]] = []
    assert drive.status() == {"configured": True, "connected": False, "email": ""}
    email = await drive.connect(browser(seen=seen), timeout=10)
    assert email == "me@example.com"
    auth = seen[0]
    assert auth["code_challenge_method"] == "S256"
    assert auth["scope"] == "https://www.googleapis.com/auth/drive.file"
    assert auth["access_type"] == "offline"
    assert auth["prompt"] == "consent"
    assert auth["redirect_uri"].startswith("http://127.0.0.1:")
    form = fake.token_forms[0]
    assert pkce_challenge(form["code_verifier"]) == auth["code_challenge"]
    assert form["client_secret"] == "csec"
    assert form["code"] == "the-code"
    assert drive.status() == {"configured": True, "connected": True, "email": "me@example.com"}

    assert await drive.list_root(5) == ["A", "B"]
    assert fake.token_forms[-1]["grant_type"] == "refresh_token"

    token_file = drive.config.gdrive_token_path
    assert token_file.exists()
    assert b"ref1" not in token_file.read_bytes() or sys.platform != "win32"
    await drive.disconnect()
    assert fake.revoked == ["ref1"]
    assert not token_file.exists()
    assert drive.status()["connected"] is False
    with pytest.raises(GoogleDriveError):
        await drive.list_root()


async def test_gdrive_wrong_state_rejected(google) -> None:
    fake, drive = google
    with pytest.raises(GoogleDriveError, match="state"):
        await drive.connect(browser(state="forged"), timeout=10)
    assert fake.token_forms == []
    assert not drive.config.gdrive_token_path.exists()


async def test_gdrive_access_denied(google) -> None:
    _fake, drive = google
    with pytest.raises(GoogleDriveError, match="afvist"):
        await drive.connect(browser(error="access_denied"), timeout=10)


async def test_gdrive_timeout_and_unconfigured(google, monkeypatch) -> None:
    _fake, drive = google
    with pytest.raises(GoogleDriveError, match="Tidsfristen"):
        await drive.connect(lambda _url: None, timeout=0.2)
    drive.config.data.pop("gdrive_client_id")
    assert drive.status()["configured"] is False
    with pytest.raises(GoogleDriveError, match="Cloud Console|Google Cloud"):
        await drive.connect(lambda _url: None)
    monkeypatch.setenv("H4XTOR_GDRIVE_CLIENT_ID", "from-env")
    assert drive.status()["configured"] is True
    assert drive.client_id == "from-env"


def test_gdrive_token_file_round_trip(tmp_path: Path) -> None:
    drive = GoogleDrive(Config(tmp_path / "c" / "config.json"))
    assert drive._load_tokens() is None
    drive._save_tokens("refresh-secret", "me@example.com")
    raw = drive.config.gdrive_token_path.read_bytes()
    if sys.platform == "win32":
        assert b"refresh-secret" not in raw  # DPAPI-encrypted
    assert drive._load_tokens() == {"refresh_token": "refresh-secret", "email": "me@example.com"}


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_dpapi_round_trip() -> None:
    blob = gdrive_mod._dpapi(b"hello", True)
    assert blob != b"hello"
    assert gdrive_mod._dpapi(blob, False) == b"hello"
