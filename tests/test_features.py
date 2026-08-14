from __future__ import annotations

import socket
from pathlib import Path
from unittest import mock

import pytest

from h4xtor_share import openers as openers_mod
from h4xtor_share.client import PeerClient
from h4xtor_share.config import Config
from h4xtor_share.crypto import ensure_certificate, server_ssl_context
from h4xtor_share.history import HistoryStore, is_link
from h4xtor_share.models import Peer, PeerStatus, signal_bars
from h4xtor_share.openers import open_path, reveal_in_folder
from h4xtor_share.server import ShareServer


def available_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def sample_peer() -> Peer:
    return Peer(
        device_id="ab" * 16,
        name="TestBox",
        address="192.168.1.20",
        port=47474,
        fingerprint="cd" * 32,
        platform="linux",
    )


def test_signal_bars_levels() -> None:
    assert signal_bars(None) == ""
    assert signal_bars(5.0) == "▂▄▆█"
    assert signal_bars(25.0) == "▂▄▆"
    assert signal_bars(60.0) == "▂▄"
    assert signal_bars(500.0) == "▂"


def test_is_link_detects_urls_only() -> None:
    assert is_link("https://example.com/path")
    assert is_link("http://localhost:8080")
    assert not is_link("not a url")
    assert not is_link("hello https://example.com world")


def test_history_store_round_trip(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    peer = sample_peer()
    store.record_sent_file(peer, "a.bin", 10, "/tmp/a.bin")
    store.record_received_text(peer, "https://example.com")
    store.record_connection(peer, True, 12.0)
    store.record_connection(peer, False)

    restored = HistoryStore(tmp_path / "history.json")
    sent = restored.sent()
    assert len(sent) == 1
    assert sent[0]["kind"] == "file"
    assert sent[0]["peer"] == "TestBox"
    received = restored.received()
    assert received[0]["kind"] == "link"
    devices = restored.devices()
    assert len(devices) == 1
    assert devices[0]["ip"] == "192.168.1.20"
    assert devices[0]["os"] == "linux"
    assert devices[0]["connections"] == 1
    assert devices[0]["online"] is False


def test_history_store_caps_entries(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    peer = sample_peer()
    for index in range(600):
        store.record_sent_file(peer, f"f{index}.txt", index, "/tmp/x")
    assert len(store.sent()) == 500


def test_peer_status_dataclass() -> None:
    status = PeerStatus(device_id="x", online=True, rtt_ms=8.5)
    assert status.online is True
    assert status.rtt_ms == 8.5


def test_open_path_linux_xdg(tmp_path: Path) -> None:
    target = tmp_path / "runme.sh"
    target.write_text("#!/bin/sh\necho hi\n")
    with mock.patch(
        "h4xtor_share.openers._IS_WINDOWS", False
    ), mock.patch(
        "h4xtor_share.openers._IS_MACOS", False
    ), mock.patch("h4xtor_share.openers._start_detached") as launch:
        open_path(target)
    launch.assert_called_once_with(["xdg-open", str(target.resolve())])
    assert target.stat().st_mode & 0o100


def test_open_path_rejects_native_windows_types_on_linux(tmp_path: Path) -> None:
    target = tmp_path / "setup.exe"
    target.write_bytes(b"MZ")
    with mock.patch(
        "h4xtor_share.openers._IS_WINDOWS", False
    ), mock.patch("h4xtor_share.openers._IS_MACOS", False), pytest.raises(RuntimeError):
        open_path(target)


def test_open_path_windows_uses_startfile(tmp_path: Path) -> None:
    target = tmp_path / "tool.exe"
    target.write_bytes(b"MZ")
    with mock.patch(
        "h4xtor_share.openers._IS_WINDOWS", True
    ), mock.patch(
        "h4xtor_share.openers._IS_MACOS", False
    ), mock.patch.object(
        openers_mod.os, "startfile", create=True, new=mock.Mock()
    ) as startfile:
        open_path(target)
    startfile.assert_called_once_with(str(target.resolve()))


def test_reveal_in_folder_uses_parent(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("x")
    with mock.patch(
        "h4xtor_share.openers._IS_WINDOWS", False
    ), mock.patch(
        "h4xtor_share.openers._IS_MACOS", False
    ), mock.patch("h4xtor_share.openers._start_detached") as launch:
        reveal_in_folder(target)
    launch.assert_called_once_with(["xdg-open", str(tmp_path.resolve())])


def test_open_path_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_path(tmp_path / "does-not-exist")


@pytest.mark.asyncio
async def test_ping_endpoint_round_trip(tmp_path: Path) -> None:
    config = Config(tmp_path / "config.json")
    config.data["port"] = available_tcp_port()
    config.save()
    certificate, key, fingerprint = ensure_certificate(config.path.parent, "Ping")
    server = ShareServer(
        config,
        server_ssl_context(certificate, key),
        fingerprint,
        lambda _event: None,
    )
    await server.start()
    try:
        client = PeerClient(config)
        peer = await client.get_info("127.0.0.1", config.port)
        rtt_ms = await client.ping(peer)
        assert 0.0 <= rtt_ms < 2000.0
    finally:
        await server.stop()
