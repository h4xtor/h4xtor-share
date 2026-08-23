from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import pytest

from h4xtor_share.config import Config
from h4xtor_share.models import Peer
from h4xtor_share.udp import (
    UdpDiscovery,
    encode_announcement,
    peer_from_announcement,
)


def available_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _config(path: Path, device_id: str) -> Config:
    config = Config(path)
    config.data["device_id"] = device_id
    config.data["device_name"] = f"device-{device_id[:4]}"
    config.data["port"] = available_udp_port()
    config.save()
    return config


def test_encode_announcement_round_trips(tmp_path: Path) -> None:
    config = _config(tmp_path / "config.json", "ab" * 16)
    encoded = encode_announcement(config, "cd" * 32, ("clipboard", "files", "folders"))
    payload = json.loads(encoded.decode("utf-8"))
    peer = peer_from_announcement(payload, "192.168.1.9")
    assert peer.device_id == config.device_id
    assert peer.address == "192.168.1.9"
    assert peer.port == config.port
    assert peer.fingerprint == "cd" * 32
    assert peer.capabilities == ("clipboard", "files", "folders")


def test_peer_from_announcement_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        peer_from_announcement({"protocol": 1}, "127.0.0.1")
    with pytest.raises(ValueError):
        peer_from_announcement({"protocol": 99, "device_id": "x" * 32}, "127.0.0.1")
    with pytest.raises(ValueError):
        peer_from_announcement("not-a-dict", "127.0.0.1")


@pytest.mark.parametrize("platform", ["windows", "macos", "linux", "android"])
def test_peer_from_announcement_accepts_any_platform(tmp_path: Path, platform: str) -> None:
    config = _config(tmp_path / f"config-{platform}.json", "ef" * 16)
    encoded = encode_announcement(config, "ff" * 32, ())
    payload = json.loads(encoded.decode("utf-8"))
    payload["platform"] = platform
    peer = peer_from_announcement(payload, "10.0.0.4")
    assert peer.platform == platform


def test_udp_discovery_receives_announcement(tmp_path: Path) -> None:
    local = _config(tmp_path / "local.json", "ab" * 16)
    remote = _config(tmp_path / "remote.json", "cd" * 16)

    received: list[Peer] = []
    discovery = UdpDiscovery(local, "beef" * 16, ("files",), received.append)
    discovery.start()
    try:
        datagram = encode_announcement(
            remote,
            "face" * 16,
            ("clipboard", "files"),
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            deadline = time.monotonic() + 3.0
            while not received and time.monotonic() < deadline:
                sender.sendto(datagram, ("127.0.0.1", local.port))
                time.sleep(0.05)

        assert received, "Listener did not deliver the announcement"
        peer = received[0]
        assert peer.device_id == remote.device_id
        assert peer.address == "127.0.0.1"
        assert peer.capabilities == ("clipboard", "files")
    finally:
        discovery.stop()


def test_udp_discovery_ignores_own_announcement(tmp_path: Path) -> None:
    local = _config(tmp_path / "local.json", "ab" * 16)
    received: list[Peer] = []
    discovery = UdpDiscovery(local, "beef" * 16, ("files",), received.append)
    discovery.start()
    try:
        datagram = encode_announcement(local, "beef" * 16, ("files",))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(datagram, ("127.0.0.1", local.port))

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            time.sleep(0.05)

        assert received == []
    finally:
        discovery.stop()
