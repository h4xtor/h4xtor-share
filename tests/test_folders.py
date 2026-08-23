from __future__ import annotations

import socket
from pathlib import Path

import pytest

from h4xtor_share.client import PeerClient
from h4xtor_share.config import Config
from h4xtor_share.crypto import ensure_certificate, server_ssl_context
from h4xtor_share.models import FolderReceived, PairingPrompt, Peer
from h4xtor_share.server import ShareServer, safe_relative_path


def available_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("file.txt", "file.txt"),
        ("a/b/c.txt", "a/b/c.txt"),
        ("./docs/report.pdf", "docs/report.pdf"),
        ("sub dir\\nested\\data.bin", "sub dir/nested/data.bin"),
        ("../escape.txt", None),
        ("/etc/passwd", "etc/passwd"),
        ("a/../../b", None),
        ("CON/notes.txt", "_CON/notes.txt"),
        ("a//b.txt", "a/b.txt"),
    ],
)
def test_safe_relative_path(value: str, expected: str | None) -> None:
    if expected is None:
        with pytest.raises(ValueError):
            safe_relative_path(value)
    else:
        assert safe_relative_path(value) == expected


async def _start_pairing(
    tmp_path: Path,
) -> tuple[ShareServer, PeerClient, Peer, list[object]]:
    receiver_config = Config(tmp_path / "receiver" / "config.json")
    receiver_config.data["device_name"] = "Receiver"
    receiver_config.data["port"] = available_tcp_port()
    receiver_config.data["incoming_directory"] = str(tmp_path / "received")
    receiver_config.save()

    certificate, key, fingerprint = ensure_certificate(
        receiver_config.path.parent,
        receiver_config.device_name,
    )
    events: list[object] = []
    server = ShareServer(
        receiver_config,
        server_ssl_context(certificate, key),
        fingerprint,
        events.append,
    )
    await server.start()

    sender_config = Config(tmp_path / "sender" / "config.json")
    sender_config.data["device_name"] = "Sender"
    sender_config.save()
    client = PeerClient(sender_config)
    peer = await client.get_info("127.0.0.1", receiver_config.port)
    pairing = await client.request_pairing(peer)
    prompt = next(event for event in events if isinstance(event, PairingPrompt))
    await client.confirm_pairing(peer, str(pairing["pairing_id"]), prompt.code)
    return server, client, peer, events


@pytest.mark.asyncio
async def test_info_advertises_folder_capability(tmp_path: Path) -> None:
    server, client, peer, _events = await _start_pairing(tmp_path)
    try:
        assert "folders" in peer.capabilities
        assert peer.supports_folders is True
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_send_folder_recreates_nested_structure(tmp_path: Path) -> None:
    server, client, peer, events = await _start_pairing(tmp_path)
    try:
        source = tmp_path / "photos"
        (source / "vacation").mkdir(parents=True)
        (source / "vacation" / "beach.txt").write_text("beach", encoding="utf-8")
        (source / "vacation" / "hotel.txt").write_text("hotel", encoding="utf-8")
        (source / "assets").mkdir()
        (source / "assets" / "logo.txt").write_text("logo", encoding="utf-8")
        (source / "readme.md").write_text("readme", encoding="utf-8")

        progress: list[object] = []
        await client.send_folder(peer, source, progress.append)

        event = next(item for item in events if isinstance(item, FolderReceived))
        destination = Path(event.path)
        assert destination.name == "photos"
        assert (
            destination / "vacation" / "beach.txt"
        ).read_text(encoding="utf-8") == "beach"
        assert (
            destination / "vacation" / "hotel.txt"
        ).read_text(encoding="utf-8") == "hotel"
        assert (
            destination / "assets" / "logo.txt"
        ).read_text(encoding="utf-8") == "logo"
        assert (destination / "readme.md").read_text(encoding="utf-8") == "readme"
        assert event.size == 20
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_send_folder_rejects_empty_folder(tmp_path: Path) -> None:
    server, client, peer, _events = await _start_pairing(tmp_path)
    try:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ValueError):
            await client.send_folder(peer, empty, lambda _progress: None)
    finally:
        await server.stop()
