from __future__ import annotations

import socket
from pathlib import Path

import pytest

from h4xtor_share.client import PeerClient
from h4xtor_share.config import Config
from h4xtor_share.crypto import ensure_certificate, server_ssl_context
from h4xtor_share.models import (
    ClipboardReceived,
    LinkReceived,
    PairingPrompt,
    PeerForgotten,
    PeerPaired,
    WifiDirectOffer,
)
from h4xtor_share.pairing import PairingInvite, parse_invite, qr_matrix
from h4xtor_share.server import ShareServer, is_safe_url
from h4xtor_share.wifidirect import windows_profile_xml


def available_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class Node:
    """A complete endpoint: config, certificate, server and client."""

    def __init__(self, root: Path, name: str) -> None:
        self.config = Config(root / name / "config.json")
        self.config.data["device_name"] = name
        self.config.data["port"] = available_tcp_port()
        self.config.data["incoming_directory"] = str(root / name / "incoming")
        self.config.save()
        certificate, key, self.fingerprint = ensure_certificate(self.config.path.parent, name)
        self.events: list[object] = []
        self.server = ShareServer(
            self.config,
            server_ssl_context(certificate, key),
            self.fingerprint,
            self.events.append,
            host="127.0.0.1",
        )
        self.client = PeerClient(self.config, fingerprint=self.fingerprint)

    def invite(self) -> PairingInvite:
        return PairingInvite(
            device_id=self.config.device_id,
            name=self.config.device_name,
            fingerprint=self.fingerprint,
            port=self.config.port,
            addresses=("127.0.0.1",),
            secret=self.server.create_qr_secret(),
            platform="linux",
        )


@pytest.fixture
async def nodes(tmp_path: Path):
    alpha = Node(tmp_path, "Alpha")
    beta = Node(tmp_path, "Beta")
    await alpha.server.start()
    await beta.server.start()
    try:
        yield alpha, beta
    finally:
        await alpha.server.stop()
        await beta.server.stop()


async def test_code_pairing_is_mutual(nodes) -> None:
    alpha, beta = nodes
    peer_beta = await alpha.client.get_info("127.0.0.1", beta.config.port)
    response = await alpha.client.request_pairing(peer_beta)
    prompt = next(event for event in beta.events if isinstance(event, PairingPrompt))
    await alpha.client.confirm_pairing(peer_beta, str(response["pairing_id"]), prompt.code)

    paired = next(event for event in beta.events if isinstance(event, PeerPaired))
    assert paired.mutual
    assert paired.peer.device_id == alpha.config.device_id
    assert paired.peer.fingerprint == alpha.fingerprint
    assert paired.peer.port == alpha.config.port

    # Beta can now send back to Alpha without pairing a second time.
    await beta.client.send_clipboard(paired.peer, "back channel")
    received = next(event for event in alpha.events if isinstance(event, ClipboardReceived))
    assert received.text == "back channel"
    assert beta.config.known_peers()[0].device_id == alpha.config.device_id


async def test_qr_pairing_is_instant_and_one_time(nodes) -> None:
    alpha, beta = nodes
    invite = beta.invite()
    parsed = parse_invite(invite.to_uri())
    assert parsed == invite

    peer = await alpha.client.pair_with_qr(parsed)
    assert peer.device_id == beta.config.device_id
    assert alpha.config.is_trusted(beta.config.device_id)
    assert beta.config.is_trusted(alpha.config.device_id)
    assert not any(isinstance(event, PairingPrompt) for event in beta.events)

    with pytest.raises(RuntimeError, match="expired"):
        await alpha.client.pair_with_qr(parsed)


async def test_qr_pairing_rejects_wrong_fingerprint(nodes) -> None:
    alpha, beta = nodes
    invite = beta.invite()
    forged = PairingInvite(
        device_id=invite.device_id,
        name=invite.name,
        fingerprint="00" * 32,
        port=invite.port,
        addresses=invite.addresses,
        secret=invite.secret,
    )
    with pytest.raises(RuntimeError):
        await alpha.client.pair_with_qr(forged)
    assert not alpha.config.is_trusted(beta.config.device_id)


async def test_link_wifi_offer_and_unpair(nodes) -> None:
    alpha, beta = nodes
    peer = await alpha.client.pair_with_qr(beta.invite())

    await alpha.client.send_link(peer, "https://example.com/watch?v=1")
    link = next(event for event in beta.events if isinstance(event, LinkReceived))
    assert link.url == "https://example.com/watch?v=1"
    assert link.peer_name == "Alpha"

    with pytest.raises(RuntimeError, match="http"):
        await alpha.client.send_link(peer, "javascript:alert(1)")

    await alpha.client.send_wifi_direct_offer(
        peer, "DIRECT-h4-test", "secretpass1", "192.168.49.1", 47474
    )
    offer = next(event for event in beta.events if isinstance(event, WifiDirectOffer))
    assert offer.ssid == "DIRECT-h4-test"
    assert offer.passphrase == "secretpass1"

    await alpha.client.unpair(peer)
    assert not alpha.config.is_trusted(beta.config.device_id)
    assert not beta.config.is_trusted(alpha.config.device_id)
    assert any(isinstance(event, PeerForgotten) for event in beta.events)


def test_invite_parser_rejects_garbage() -> None:
    for bad in (
        "https://example.com",
        "h4xtor://pair?v=1&id=zz",
        "h4xtor://pair?v=2",
        "h4xtor://pair?v=1&id=" + "a" * 32 + "&fp=" + "b" * 64 + "&p=1&a=&s=" + "x" * 20,
    ):
        with pytest.raises(ValueError):
            parse_invite(bad)


def test_invite_round_trips_unicode_names() -> None:
    invite = PairingInvite(
        device_id="a" * 32,
        name="Lennarts PC – kontor & æøå",
        fingerprint="b" * 64,
        port=47474,
        addresses=("192.168.1.10", "192.168.49.23"),
        secret="s" * 24,
        platform="windows",
    )
    assert parse_invite(invite.to_uri()) == invite
    matrix = qr_matrix(invite.to_uri())
    assert len(matrix) == len(matrix[0]) >= 21


def test_safe_url_and_wifi_profile() -> None:
    assert is_safe_url("https://a.dk/x")
    assert not is_safe_url("file:///etc/passwd")
    assert not is_safe_url("https://a.dk/ x")
    xml = windows_profile_xml("DIRECT-<&>", "pass&word")
    assert "DIRECT-&lt;&amp;&gt;" in xml
    assert "pass&amp;word" in xml


async def test_ping_rejects_a_different_device_on_the_same_address(nodes) -> None:
    from dataclasses import replace

    alpha, beta = nodes
    peer = await alpha.client.get_info("127.0.0.1", beta.config.port)
    assert await alpha.client.ping(peer) >= 0
    impostor = replace(peer, device_id="ff" * 16)
    with pytest.raises(RuntimeError):
        await alpha.client.ping(impostor)


async def test_speedtest_measures_and_stores_nothing(nodes) -> None:
    alpha, beta = nodes
    peer = await alpha.client.pair_with_qr(parse_invite(beta.invite().to_uri()))
    inbox = beta.config.incoming_directory
    before = set(inbox.rglob("*")) if inbox.exists() else set()
    speed = await alpha.client.speed_test(peer, 4 * 1024 * 1024)
    assert speed > 0
    after = set(inbox.rglob("*")) if inbox.exists() else set()
    assert after == before
