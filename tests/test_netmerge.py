from __future__ import annotations

import asyncio
import socket
import struct
from pathlib import Path

import pytest

from h4xtor_share.crypto import ensure_certificate, server_ssl_context
from h4xtor_share.netmerge import (
    Link,
    NetMerge,
    PhoneRoute,
    parse_target,
    rewrite_http_request,
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def origin_server():
    """Tiny web server: /generate_204 answers 204, everything else echoes the request line."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        line = head.split(b"\r\n", 1)[0]
        if b"/generate_204" in line:
            writer.write(b"HTTP/1.1 204 No Content\r\n\r\n")
        elif b"/big" in line:
            body = b"x" * (1024 * 1024)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        else:
            body = line + b"|" + head
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def fake_phone(tmp_path: Path, token: str):
    """The phone side: TLS, Bearer auth, CONNECT tunnel (what the Android app does over 5G)."""
    cert, key, fingerprint = ensure_certificate(tmp_path / "phone", "phone")
    seen: list[str] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode()
        seen.append(head)
        method, target = head.split(" ")[:2]
        if method != "CONNECT" or f"Bearer {token}" not in head:
            writer.write(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        host, port = target.rsplit(":", 1)
        up_reader, up_writer = await asyncio.open_connection(host, int(port))
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")

        async def pump(src, dst):
            while data := await src.read(65536):
                dst.write(data)
                await dst.drain()
            dst.close()

        await asyncio.gather(pump(reader, up_writer), pump(up_reader, writer))

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ssl_context(cert, key))
    return server, server.sockets[0].getsockname()[1], fingerprint, seen


@pytest.fixture
async def origin():
    server, port = await origin_server()
    yield port
    server.close()


async def make_merge(origin_port: int, adapters=None) -> NetMerge:
    merge = NetMerge(
        free_port(),
        probe=("127.0.0.1", origin_port),
        adapters=adapters or (lambda: [("Loopback", "127.0.0.1")]),
    )
    await merge.start()
    await merge.probe_all()
    return merge


async def http_via_proxy(port: int, raw: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw)
    await writer.drain()
    data = await reader.read()
    writer.close()
    return data


def test_parse_target_and_rewrite() -> None:
    assert parse_target("example.com:8443", 443) == ("example.com", 8443)
    assert parse_target("example.com", 443) == ("example.com", 443)
    assert parse_target("[::1]:80", 443) == ("::1", 80)
    with pytest.raises(ValueError):
        parse_target("example.com:99999", 443)
    host, port, head = rewrite_http_request(
        b"GET http://example.com:8080/a?b=1 HTTP/1.1\r\nHost: example.com\r\n"
        b"Proxy-Connection: keep-alive\r\nAccept: */*\r\n\r\n"
    )
    assert (host, port) == ("example.com", 8080)
    assert head.startswith(b"GET /a?b=1 HTTP/1.1\r\n")
    assert b"Proxy-Connection" not in head and b"Connection: close" in head
    with pytest.raises(ValueError):
        rewrite_http_request(b"GET ftp://x/ HTTP/1.1\r\n\r\n")


async def test_connect_plain_http_socks_and_pac(origin: int) -> None:
    merge = await make_merge(origin)
    try:
        link = merge.links["pc:127.0.0.1"]
        assert link.healthy and link.latency is not None

        tunnel = await http_via_proxy(
            merge.port,
            f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\n\r\n".encode()
            + b"GET /hello HTTP/1.1\r\nHost: x\r\n\r\n",
        )
        assert tunnel.startswith(b"HTTP/1.1 200 Connection established")
        assert b"GET /hello" in tunnel

        plain = await http_via_proxy(
            merge.port,
            f"GET http://127.0.0.1:{origin}/page HTTP/1.1\r\nHost: x\r\n\r\n".encode(),
        )
        assert b"GET /page HTTP/1.1|" in plain and b"Connection: close" in plain

        reader, writer = await asyncio.open_connection("127.0.0.1", merge.port)
        writer.write(b"\x05\x01\x00")
        assert await reader.readexactly(2) == b"\x05\x00"
        name = b"localhost"
        writer.write(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack("!H", origin))
        assert (await reader.readexactly(10))[:2] == b"\x05\x00"
        writer.write(b"GET /socks HTTP/1.1\r\nHost: x\r\n\r\n")
        assert b"GET /socks" in await reader.read()
        writer.close()

        pac = await http_via_proxy(merge.port, b"GET /proxy.pac HTTP/1.1\r\nHost: x\r\n\r\n")
        assert f"PROXY 127.0.0.1:{merge.port}; DIRECT".encode() in pac
        assert link.connections == 3 and link.received > 0 and link.active == 0
    finally:
        await merge.stop()


async def test_phone_link_tunnels_with_pinned_tls(origin: int, tmp_path: Path) -> None:
    server, port, fingerprint, seen = await fake_phone(tmp_path, "secret-token")
    merge = await make_merge(origin, adapters=lambda: [])
    try:
        route = PhoneRoute("127.0.0.1", port, fingerprint, {"Authorization": "Bearer secret-token"})
        merge.set_phone("phone1", "Pixel", route)
        await merge.probe_all()
        link = merge.links["phone:phone1"]
        assert link.healthy and link.name == "Pixel"
        data = await http_via_proxy(
            merge.port,
            f"GET http://127.0.0.1:{origin}/via-phone HTTP/1.1\r\nHost: x\r\n\r\n".encode(),
        )
        assert b"GET /via-phone" in data
        assert any(f"CONNECT 127.0.0.1:{origin}" in head for head in seen)
        assert link.received > 0

        # A wrong pin (someone else's device on the Wi-Fi) must never be used.
        merge.set_phone("phone1", "Pixel", PhoneRoute("127.0.0.1", port, "00" * 32, route.headers))
        await merge.probe_all()
        assert not merge.links["phone:phone1"].healthy
        # A wrong token is refused by the phone.
        merge.set_phone("phone1", "Pixel", PhoneRoute("127.0.0.1", port, fingerprint, {}))
        await merge.probe_all()
        assert not merge.links["phone:phone1"].healthy

        merge.set_phone("phone1", "Pixel", None)
        assert "phone:phone1" not in merge.links
    finally:
        await merge.stop()
        server.close()


def test_speed_samples_stay_bounded_while_nobody_reads_them(monkeypatch) -> None:
    clock = [100.0]
    monkeypatch.setattr("h4xtor_share.netmerge.time.monotonic", lambda: clock[0])
    link = Link("a", "Wi-Fi", "pc")
    for _ in range(1000):  # hours of traffic with the Wi-Fi + 5G page closed, compressed
        link.count(1000)
        clock[0] += 0.25
    assert link.received == 1_000_000
    assert len(link._window) <= 13  # three seconds of samples, not the whole history
    assert link.speed() == 4000  # the 12 samples of the last three seconds


async def test_phone_tunnel_ends_when_the_client_leaves(origin: int, tmp_path: Path) -> None:
    server, port, fingerprint, _seen = await fake_phone(tmp_path, "t")
    held: list[asyncio.StreamWriter] = []
    # A server that keeps an idle connection open and never says anything (keep-alive).
    idle = await asyncio.start_server(lambda _r, w: held.append(w), "127.0.0.1", 0)
    merge = await make_merge(origin, adapters=lambda: [])
    try:
        route = PhoneRoute("127.0.0.1", port, fingerprint, {"Authorization": "Bearer t"})
        merge.set_phone("phone1", "Pixel", route)
        await merge.probe_all()
        link = merge.links["phone:phone1"]
        idle_port = idle.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", merge.port)
        writer.write(f"CONNECT 127.0.0.1:{idle_port} HTTP/1.1\r\n\r\n".encode())
        assert (await reader.readuntil(b"\r\n\r\n")).startswith(b"HTTP/1.1 200")
        assert link.active == 1
        writer.close()  # the browser drops the connection
        for _ in range(100):
            if link.active == 0:
                break
            await asyncio.sleep(0.05)
        assert link.active == 0  # the tunnel to the phone ended with it
    finally:
        await merge.stop()
        server.close()
        idle.close()
        for item in held:
            item.close()


async def test_balancing_prefers_fast_links_and_falls_back(origin: int) -> None:
    merge = NetMerge(free_port(), adapters=lambda: [])
    fast, slow = Link("a", "Wi-Fi", "pc", healthy=True), Link("b", "5G", "pc", healthy=True)
    fast.rate, slow.rate = 30e6, 10e6
    merge.links = {"a": fast, "b": slow}
    picks = []
    for _ in range(8):  # simulate 8 open connections
        best = merge.ranked()[0]
        best.active += 1
        picks.append(best.key)
    assert picks.count("a") == 6 and picks.count("b") == 2

    # No healthy link (or every link fails): the default route still works.
    merge.links = {"c": Link("c", "Dead", "pc", bind="127.0.0.1", healthy=False)}
    link, reader, writer = await merge.dial("127.0.0.1", origin)
    assert link is None
    writer.close()
    broken = Link("d", "Broken", "pc", bind="203.0.113.9", healthy=True)
    merge.links = {"d": broken}
    link, _reader, writer = await merge.dial("127.0.0.1", origin)
    assert link is None and broken.failures == 1 and broken.active == 0
    writer.close()


async def test_big_transfer_teaches_link_speed(origin: int) -> None:
    merge = await make_merge(origin)
    try:
        link = merge.links["pc:127.0.0.1"]
        before = link.rate
        data = await http_via_proxy(
            merge.port, f"GET http://127.0.0.1:{origin}/big HTTP/1.1\r\nHost: x\r\n\r\n".encode()
        )
        assert len(data) > 1024 * 1024
        await asyncio.sleep(0.05)
        assert link.received >= 1024 * 1024 and link.rate != before
    finally:
        await merge.stop()
