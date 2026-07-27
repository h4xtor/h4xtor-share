from __future__ import annotations

import socket
from pathlib import Path

import pytest

from h4xtor_share.client import PeerClient
from h4xtor_share.config import Config
from h4xtor_share.crypto import ensure_certificate, server_ssl_context
from h4xtor_share.models import ClipboardReceived, FileReceived, PairingPrompt
from h4xtor_share.server import ShareServer


def available_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.mark.asyncio
async def test_pair_clipboard_and_streamed_file_transfer(tmp_path: Path) -> None:
    receiver_config = Config(tmp_path / "receiver" / "config.json")
    receiver_config.data["device_name"] = "Receiver"
    receiver_config.data["port"] = available_tcp_port()
    receiver_config.data["incoming_directory"] = str(tmp_path / "received")
    receiver_config.save()

    sender_config = Config(tmp_path / "sender" / "config.json")
    sender_config.data["device_name"] = "Sender"
    sender_config.save()

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

    try:
        client = PeerClient(sender_config)
        peer = await client.get_info("127.0.0.1", receiver_config.port)
        assert peer.device_id == receiver_config.device_id
        assert peer.fingerprint == fingerprint

        pairing_response = await client.request_pairing(peer)
        prompt = next(event for event in events if isinstance(event, PairingPrompt))
        await client.confirm_pairing(
            peer,
            str(pairing_response["pairing_id"]),
            prompt.code,
        )

        await client.send_clipboard(peer, "offline clipboard")
        clipboard_event = next(
            event for event in events if isinstance(event, ClipboardReceived)
        )
        assert clipboard_event.peer_name == "Sender"
        assert clipboard_event.text == "offline clipboard"

        payload = bytes(range(256)) * 10_000
        source = tmp_path / "arbitrary-file.custom-extension"
        source.write_bytes(payload)
        await client.send_file(peer, source, lambda _event: None)

        file_event = next(event for event in events if isinstance(event, FileReceived))
        assert file_event.peer_name == "Sender"
        assert file_event.size == len(payload)
        assert file_event.path.name == source.name
        assert file_event.path.read_bytes() == payload
    finally:
        await server.stop()
