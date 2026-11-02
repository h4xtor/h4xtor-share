"""An AI steers the phone: MCP server → desktop loopback API → (fake) phone."""

from __future__ import annotations

import asyncio
import base64
import json
import socket
from pathlib import Path
from typing import Any

import pytest

from h4xtor_share.config import Config
from h4xtor_share.local_api import LOCAL_API_PORT_OFFSET, LocalApi
from h4xtor_share.mcp_phone import TOOLS, PhoneBridge, handle, setup_json

PHONE = "a" * 32
PIXEL = base64.b64encode(b"\xff\xd8 fake jpeg").decode("ascii")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def setup(tmp_path: Path):
    config = Config(tmp_path / "config.json")
    config.data["port"] = free_port() - LOCAL_API_PORT_OFFSET
    asked: list[str] = []
    calls: list[tuple[str, dict[str, Any]]] = []
    phone = {"seq": 0, "waiting": 2}

    async def approver(name: str, _origin: str) -> bool:
        asked.append(name)
        return True

    async def control(device_id: str, op: str, body: dict[str, Any]) -> dict[str, Any]:
        assert device_id == PHONE
        calls.append((op, body))
        if op == "screen":
            if phone["waiting"]:  # the user has not tapped "Start nu" yet
                phone["waiting"] -= 1
                return {"active": False, "waiting": True}
            phone["seq"] += 1
            return {"active": True, "seq": phone["seq"], "width": 480, "height": 960,
                    "format": "jpeg", "image": PIXEL}
        return {"ok": True}

    async def sender(*_args: Any) -> None:
        return None

    devices = [{"id": PHONE, "name": "S24", "platform": "android", "online": True}]
    api = LocalApi(config, config.port + LOCAL_API_PORT_OFFSET, lambda: devices, sender,
                   approver, phone=control)
    await api.start()
    try:
        yield config, PhoneBridge(config), asked, calls
    finally:
        await api.stop()


def call(bridge: PhoneBridge, name: str, **arguments: Any) -> dict[str, Any]:
    answer = handle(bridge, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": name, "arguments": arguments}})
    assert answer is not None
    return answer["result"]


async def test_ai_control_is_off_until_switched_on(setup) -> None:
    _config, bridge, asked, calls = setup
    result = await asyncio.to_thread(call, bridge, "phone_screen")
    assert result["isError"] and "slået fra" in result["content"][0]["text"]
    assert asked == ["AI (MCP)"]  # approved once, the token is kept
    assert calls == []


async def test_ai_sees_and_taps_the_phone(setup, monkeypatch) -> None:
    config, bridge, asked, calls = setup
    config.set_flag("ai_control", True)
    monkeypatch.setattr("h4xtor_share.mcp_phone.time.sleep", lambda _s: None)

    result = await asyncio.to_thread(call, bridge, "phone_screen")
    image, text = result["content"]
    assert image == {"type": "image", "data": PIXEL, "mimeType": "image/jpeg"}
    assert "480x960" in text["text"]
    assert [op for op, _ in calls] == ["start", "screen", "screen", "screen"]

    calls.clear()
    result = await asyncio.to_thread(call, bridge, "phone_tap", x=240, y=240)
    assert "isError" not in result
    op, body = calls[0]
    assert op == "input" and body["action"] == {"type": "tap", "x": 0.5, "y": 0.25}
    assert calls[1] == ("screen", {"device_id": PHONE, "after": 1})  # a fresh picture

    calls.clear()
    await asyncio.to_thread(call, bridge, "phone_button", button="home")
    await asyncio.to_thread(call, bridge, "phone_type", text="hej")
    await asyncio.to_thread(call, bridge, "phone_stop")
    actions = [body.get("action") for op, body in calls if op == "input"]
    assert actions == [{"type": "home"}, {"type": "text", "text": "hej"}]
    assert calls[-1][0] == "stop"
    assert asked == ["AI (MCP)"]

    bad = await asyncio.to_thread(call, bridge, "phone_button", button="power")
    assert bad["isError"]


def test_mcp_handshake_and_setup() -> None:
    bridge = PhoneBridge.__new__(PhoneBridge)
    hello = handle(bridge, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                            "params": {"protocolVersion": "2025-06-18"}})
    assert hello is not None and hello["result"]["capabilities"] == {"tools": {}}
    assert handle(bridge, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    listed = handle(bridge, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed is not None and listed["result"]["tools"] is TOOLS
    server = json.loads(setup_json())["mcpServers"]["h4xtor-phone"]
    assert server["args"][-1] == "--mcp"
