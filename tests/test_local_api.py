from __future__ import annotations

import socket
from pathlib import Path

import aiohttp
import pytest

from h4xtor_share.config import Config
from h4xtor_share.local_api import LocalApi

EXT = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def api(tmp_path: Path):
    config = Config(tmp_path / "config.json")
    sent: list[tuple[str, str, str]] = []
    decisions = {"answer": True}

    async def sender(device_id: str, kind: str, value: str) -> None:
        if value == "boom":
            raise RuntimeError("Telefonen svarer ikke")
        sent.append((device_id, kind, value))

    async def approver(_name: str, _origin: str) -> bool:
        return decisions["answer"]

    devices = [{"id": "a" * 32, "name": "S24 Ultra", "platform": "android", "online": True}]
    server = LocalApi(config, free_port(), lambda: devices, sender, approver)
    await server.start()
    try:
        yield server, sent, decisions, f"http://127.0.0.1:{server.port}"
    finally:
        await server.stop()


async def test_websites_are_blocked(api) -> None:
    _server, _sent, _decisions, base = api
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{base}/v1/status", headers={"Origin": "https://evil.example"}
        ) as response:
            assert response.status == 403
        async with session.post(
            f"{base}/v1/connect", headers={"Origin": "https://evil.example"}, json={}
        ) as response:
            assert response.status == 403


async def test_connect_list_and_send(api) -> None:
    _server, sent, decisions, base = api
    headers = {"Origin": EXT}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/v1/devices", headers=headers) as response:
            assert response.status == 401

        decisions["answer"] = False
        async with session.post(
            f"{base}/v1/connect", headers=headers, json={"name": "Chrome"}
        ) as r:
            assert r.status == 403

        decisions["answer"] = True
        async with session.post(
            f"{base}/v1/connect", headers=headers, json={"name": "Chrome"}
        ) as r:
            assert r.status == 200
            assert r.headers["Access-Control-Allow-Origin"] == EXT
            token = (await r.json())["token"]

        auth = {**headers, "Authorization": f"Bearer {token}"}
        async with session.get(f"{base}/v1/status", headers=auth) as r:
            assert (await r.json())["authorised"] is True
        async with session.get(f"{base}/v1/devices", headers=auth) as r:
            devices = (await r.json())["devices"]
            assert devices[0]["name"] == "S24 Ultra"

        body = {"device_id": "a" * 32, "kind": "link", "value": "https://example.com"}
        async with session.post(f"{base}/v1/send", headers=auth, json=body) as r:
            assert r.status == 200
        assert sent == [("a" * 32, "link", "https://example.com")]

        bad = {"device_id": "b" * 32, "kind": "link", "value": "https://x.dk"}
        async with session.post(f"{base}/v1/send", headers=auth, json=bad) as r:
            assert r.status == 404
        boom = {"device_id": "a" * 32, "kind": "text", "value": "boom"}
        async with session.post(f"{base}/v1/send", headers=auth, json=boom) as r:
            assert r.status == 502
            assert "svarer ikke" in await r.text()

        async with session.post(f"{base}/v1/disconnect", headers=auth) as r:
            assert r.status == 200
        async with session.get(f"{base}/v1/devices", headers=auth) as r:
            assert r.status == 401
