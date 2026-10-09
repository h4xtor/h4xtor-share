from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import aiohttp
import pytest

from h4xtor_share.config import Config
from h4xtor_share.models import ClipboardReceived, FileReceived, LinkReceived, TransferProgress
from h4xtor_share.web_share import WebShare, device_label

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def web(tmp_path: Path):
    config = Config(tmp_path / "config.json")
    config.incoming_directory = tmp_path / "incoming"
    config.data["web_enabled"] = True
    events: list[object] = []

    async def clipboard() -> str:
        return "fra pc"

    share = WebShare(config, free_port(), events.append, clipboard, host="127.0.0.1")
    await share.start()
    base = f"http://127.0.0.1:{share.port}"
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": IPHONE}) as session:
            yield share, events, session, base
    finally:
        await share.stop()


def test_device_label() -> None:
    assert device_label(IPHONE) == "iPhone"
    assert device_label("Mozilla/5.0 (Linux; Android 15)") == "Android"
    assert device_label("curl/8") == "Browser"


async def test_key_is_required_and_rotates(web) -> None:
    share, _events, session, base = web
    async with session.get(f"{base}/") as response:
        assert response.status == 200  # the page itself holds no secrets
        assert "h4xtor share" in await response.text()
    async with session.get(f"{base}/api/state") as response:
        assert response.status == 401
    async with session.get(f"{base}/api/state?k=wrong") as response:
        assert response.status == 401
    old = share.token
    async with session.get(f"{base}/api/state", headers={"X-H4xtor-Key": old}) as response:
        assert response.status == 200
        assert (await response.json())["pc"] == share.config.device_name
    share.new_token()
    async with session.get(f"{base}/api/state?k={old}") as response:
        assert response.status == 401  # "Nyt link" locks out old phones
    share.config.data["web_enabled"] = False
    async with session.get(f"{base}/api/state?k={share.token}") as response:
        assert response.status == 401  # switched off = closed


async def test_upload_lands_in_incoming(web) -> None:
    share, events, session, base = web
    body = b"x" * 300_000
    url = f"{base}/api/upload?name=../IMG_0001.HEIC&size={len(body)}"
    async with session.post(url, data=body, headers={"X-H4xtor-Key": share.token}) as response:
        assert response.status == 200
    saved = share.config.incoming_directory / "IMG_0001.HEIC"  # path traversal stripped
    assert saved.read_bytes() == body
    received = [event for event in events if isinstance(event, FileReceived)]
    assert received and received[0].peer_name == "iPhone"
    assert any(isinstance(event, TransferProgress) for event in events)

    short = f"{base}/api/upload?name=cut.bin&size=10"
    async with session.post(short, data=b"abc", headers={"X-H4xtor-Key": share.token}) as resp:
        assert resp.status == 400
    leftovers = list(share.config.incoming_directory.glob(".h4xtor-*"))
    assert not leftovers and not (share.config.incoming_directory / "cut.bin").exists()


async def test_text_link_and_clipboard(web) -> None:
    share, events, session, base = web
    headers = {"X-H4xtor-Key": share.token}
    async with session.post(f"{base}/api/text", json={"text": "hej"}, headers=headers) as r:
        assert (await r.json())["kind"] == "text"
    async with session.post(
        f"{base}/api/text", json={"text": "https://example.com"}, headers=headers
    ) as r:
        assert (await r.json())["kind"] == "link"
    assert isinstance(events[0], ClipboardReceived) and events[0].text == "hej"
    assert isinstance(events[1], LinkReceived)
    async with session.get(f"{base}/api/clipboard", headers=headers) as r:
        assert (await r.json())["text"] == "fra pc"


async def test_outbox_download(web, tmp_path: Path) -> None:
    share, events, session, base = web
    photo = tmp_path / "ferie billede.jpg"
    photo.write_bytes(b"jpeg-data")
    item = share.add_file(photo)
    share.add_text("kode 1234")
    async with session.get(f"{base}/api/state?k={share.token}") as r:
        outbox = (await r.json())["outbox"]
    assert [entry["kind"] for entry in outbox] == ["text", "file"]
    assert outbox[0]["text"] == "kode 1234"

    preview = f"{base}/api/files/{item.item_id}?k={share.token}&inline=1&preview=1"
    async with session.get(preview) as r:
        assert await r.read() == b"jpeg-data"
    assert item.downloads == 0  # thumbnails are not deliveries
    async with session.head(f"{base}/api/files/{item.item_id}?k={share.token}") as r:
        assert r.status == 200
    assert item.downloads == 0  # neither is a HEAD request
    async with session.get(f"{base}/api/files/{item.item_id}?k={share.token}") as r:
        assert await r.read() == b"jpeg-data"
        assert "attachment" in r.headers["Content-Disposition"]
        assert r.headers["Content-Type"] == "image/jpeg"
    for _ in range(50):  # the server counts right after its last write
        if item.downloads:
            break
        await asyncio.sleep(0.02)
    assert item.downloads == 1

    url = f"{base}/api/files/{item.item_id}?k={share.token}"
    async with session.get(url, headers={"Range": "bytes=0-3"}) as r:
        assert r.status == 206 and await r.read() == b"jpeg"
        assert r.headers["Content-Range"] == "bytes 0-3/9"
    async with session.get(url, headers={"Range": "bytes=5-"}) as r:  # resume
        assert r.status == 206 and await r.read() == b"data"
    for _ in range(50):
        if item.downloads == 2:
            break
        await asyncio.sleep(0.02)
    assert item.downloads == 2  # only the part that reached the end counts
    async with session.get(url, headers={"Range": "bytes=99-"}) as r:
        assert r.status == 416
    assert any(isinstance(e, TransferProgress) and e.direction == "send" for e in events)

    share.remove(item.item_id)
    async with session.get(f"{base}/api/files/{item.item_id}?k={share.token}") as r:
        assert r.status == 404
