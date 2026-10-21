from __future__ import annotations

import os
import socket
import socketserver
import sys
import threading
import time

import pytest

from h4xtor_share import bluetooth
from h4xtor_share.bluetooth import Bridge


class _Echo(socketserver.BaseRequestHandler):
    """Answers each connection with a tag + everything it receives (until the peer stops)."""

    def handle(self) -> None:
        self.request.sendall(self.server.tag)  # type: ignore[attr-defined]
        while data := self.request.recv(65536):
            self.request.sendall(data)


def _server(tag: bytes) -> socketserver.ThreadingTCPServer:
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Echo)
    server.daemon_threads = True
    server.tag = tag  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _roundtrip(port: int, payload: bytes, tag: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as conn:
        assert conn.recv(len(tag), socket.MSG_WAITALL) == tag
        sender = threading.Thread(target=conn.sendall, args=(payload,))
        sender.start()
        received = bytearray()
        while len(received) < len(payload):
            chunk = conn.recv(65536)
            assert chunk, "stream closed early"
            received += chunk
        sender.join()
        return bytes(received)


@pytest.fixture
def pair():
    pc_server, phone_server = _server(b"PC:"), _server(b"PHONE:")
    left, right = socket.socketpair()
    closed: list[Bridge] = []
    pc = Bridge(left, "pc-id", pc_server.server_address[1], odd=True, on_closed=closed.append)
    phone = Bridge(right, "phone-id", phone_server.server_address[1], odd=False)
    pc.start()
    phone.start()
    assert pc.wait_hello(5) == "phone-id"
    assert phone.wait_hello(5) == "pc-id"
    yield pc, phone, closed
    pc.close()
    phone.close()
    pc_server.shutdown()
    phone_server.shutdown()


def test_streams_both_ways_with_large_data(pair) -> None:
    pc, phone, _closed = pair
    big = os.urandom(3 * 1024 * 1024)
    # PC app -> pc.port -> link -> phone's own server
    assert _roundtrip(pc.port, big, b"PHONE:") == big
    # phone app -> phone.port -> link -> PC's own server
    assert _roundtrip(phone.port, b"hej fra telefonen", b"PC:") == b"hej fra telefonen"
    assert pc.opened == 2 and phone.opened == 2  # both streams, odd/even ids never collide


def test_many_streams_at_once(pair) -> None:
    pc, phone, _closed = pair
    results: list[bool] = []

    def one(index: int) -> None:
        port = pc.port if index % 2 else phone.port
        tag = b"PHONE:" if index % 2 else b"PC:"
        data = os.urandom(200_000 + index)
        results.append(_roundtrip(port, data, tag) == data)

    threads = [threading.Thread(target=one, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert results == [True] * 12


def test_link_loss_closes_everything(pair) -> None:
    pc, phone, closed = pair
    conn = socket.create_connection(("127.0.0.1", pc.port), timeout=5)
    assert conn.recv(6, socket.MSG_WAITALL) == b"PHONE:"
    phone.close()  # e.g. the phone walks out of Bluetooth range
    deadline = time.time() + 5
    while not closed and time.time() < deadline:
        time.sleep(0.05)
    assert pc.closed and closed == [pc]
    assert conn.recv(10) == b""  # the app's connection ends instead of hanging
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", pc.port), timeout=2)


def test_other_service_is_refused() -> None:
    left, right = socket.socketpair()
    right.sendall(bluetooth.encode(bluetooth.HELLO, 0, b'{"magic": "something-else"}'))
    bridge = Bridge(left, "pc-id", 1).start()
    with pytest.raises(ConnectionError):
        bridge.wait_hello(5)
    assert bridge.closed
    right.close()


def test_frame_bytes_match_the_android_bridge() -> None:
    # The same bytes are asserted in BluetoothBridgeTest.java, so both sides speak alike.
    assert bluetooth.encode(bluetooth.DATA, 7, b"hi").hex() == "0200000007000000026869"
    assert bluetooth.encode(bluetooth.CLOSE, 2).hex() == "030000000200000000"


def test_candidates_prefer_remembered_then_name() -> None:
    paired = [
        ("11:11:11:11:11:11", "WH-1000XM5"),
        ("22:22:22:22:22:22", "Galaxy S24 Ultra"),
        ("33:33:33:33:33:33", "Keyboard"),
    ]
    assert bluetooth.candidates(paired, "S24 Ultra") == ["22:22:22:22:22:22"]
    assert bluetooth.candidates(paired, "S24 Ultra", remembered="33:33:33:33:33:33") == [
        "33:33:33:33:33:33",
        "22:22:22:22:22:22",
    ]
    assert len(bluetooth.candidates(paired, "Telefon", everything=True)) == 3
    assert bluetooth.candidates(paired, "Telefon") == []


def test_windows_sockaddr_layout() -> None:
    raw = bluetooth.windows_sockaddr("AA:BB:CC:DD:EE:FF")
    assert len(raw) == 30  # sizeof(SOCKADDR_BTH) with #pragma pack(1)
    assert raw[:2] == (32).to_bytes(2, "little")
    assert raw[2:10] == (0xAABBCCDDEEFF).to_bytes(8, "little")
    assert raw[-4:] == b"\0\0\0\0"  # port 0: Windows finds the channel by service UUID


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Bluetooth sockets")
def test_windows_connect_fails_cleanly_without_the_phone() -> None:
    with pytest.raises(OSError):
        bluetooth.open_bridge("00:00:00:00:00:01", "pc-id", 1)
