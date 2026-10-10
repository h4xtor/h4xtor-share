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


async def _serve(tmp_path: Path, devices, sender_all):
    config = Config(tmp_path / "config.json")

    async def sender(_d: str, _k: str, _v: str) -> None: ...

    async def approver(_n: str, _o: str) -> bool:
        return True

    server = LocalApi(
        config, free_port(), lambda: devices, sender, approver, sender_all=sender_all
    )
    await server.start()
    async with aiohttp.ClientSession() as session, session.post(
        f"http://127.0.0.1:{server.port}/v1/connect",
        headers={"Origin": EXT},
        json={"name": "Chrome"},
    ) as r:
        token = (await r.json())["token"]
    return server, {"Origin": EXT, "Authorization": f"Bearer {token}"}


async def test_send_all(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    async def sender_all(kind: str, value: str) -> list[dict]:
        calls.append((kind, value))
        return [
            {"id": "a" * 32, "name": "S24", "ok": True, "error": ""},
            {"id": "b" * 32, "name": "Bærbar", "ok": False, "error": "Kan ikke nå Bærbar."},
        ]

    devices = [
        {"id": "a" * 32, "name": "S24", "platform": "android", "online": True},
        {"id": "b" * 32, "name": "Bærbar", "platform": "windows", "online": False},
    ]
    server, auth = await _serve(tmp_path, devices, sender_all)
    url = f"http://127.0.0.1:{server.port}/v1/send-all"
    try:
        async with aiohttp.ClientSession() as session:
            body = {"kind": "link", "value": "https://example.com"}
            async with session.post(url, headers={"Origin": EXT}, json=body) as r:
                assert r.status == 401
            async with session.post(url, headers=auth, json={"kind": "nope", "value": "x"}) as r:
                assert r.status == 400
            async with session.post(url, headers=auth, json={"kind": "text", "value": " "}) as r:
                assert r.status == 400
            big = {"kind": "text", "value": "x" * 100_001}
            async with session.post(url, headers=auth, json=big) as r:
                assert r.status == 400
            async with session.post(url, headers=auth, data="not json") as r:
                assert r.status == 400
            assert calls == []
            # Partial failure is still a 200 with one result per device.
            async with session.post(url, headers=auth, json=body) as r:
                assert r.status == 200
                results = (await r.json())["results"]
        assert [x["ok"] for x in results] == [True, False]
        assert results[1]["name"] == "Bærbar"
        assert calls == [("link", "https://example.com")]
    finally:
        await server.stop()


async def test_send_all_without_devices_or_sender(tmp_path: Path) -> None:
    async def sender_all(_k: str, _v: str) -> list[dict]:
        raise AssertionError("must not be called")

    body = {"kind": "text", "value": "hej"}
    server, auth = await _serve(tmp_path, [], sender_all)
    try:
        async with aiohttp.ClientSession() as session, session.post(
            f"http://127.0.0.1:{server.port}/v1/send-all", headers=auth, json=body
        ) as r:
            assert r.status == 404
    finally:
        await server.stop()

    one = [{"id": "a" * 32, "name": "S24", "platform": "android", "online": True}]
    server, auth = await _serve(tmp_path, one, None)  # backward-compatible: no sender_all
    try:
        async with aiohttp.ClientSession() as session, session.post(
            f"http://127.0.0.1:{server.port}/v1/send-all", headers=auth, json=body
        ) as r:
            assert r.status == 501
    finally:
        await server.stop()
