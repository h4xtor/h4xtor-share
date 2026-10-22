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


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    # Not MSG_WAITALL: Windows refuses it on sockets with a timeout (WinError 10045).
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        assert chunk, "stream closed early"
        data += chunk
    return data


def _roundtrip(port: int, payload: bytes, tag: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as conn:
        assert _recv_exact(conn, len(tag)) == tag
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
    assert not pc.busy  # hello only
    # PC app -> pc.port -> link -> phone's own server
    assert _roundtrip(pc.port, big, b"PHONE:") == big
    assert pc.busy and phone.busy  # a file is moving: the PC must not switch the link off now
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
    assert _recv_exact(conn, 6) == b"PHONE:"
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


def test_candidates_also_try_every_paired_phone() -> None:
    paired = [
        ("11:11:11:11:11:11", "WH-1000XM5", False),
        ("22:22:22:22:22:22", "Galaxy S24", True),
        ("33:33:33:33:33:33", "Lennarts telefon", True),
    ]
    # The app name ("S24 Ultra") is not the Bluetooth name: still tried, headphones left alone.
    assert bluetooth.candidates(paired, "Min mobil") == ["22:22:22:22:22:22", "33:33:33:33:33:33"]
    assert bluetooth.candidates(paired, "telefon", remembered="22:22:22:22:22:22") == [
        "22:22:22:22:22:22",
        "33:33:33:33:33:33",
    ]


def test_scan_targets_prefer_phones() -> None:
    paired = [("11:11:11:11:11:11", "WH", False), ("22:22:22:22:22:22", "S24", True)]
    assert bluetooth.scan_targets(paired) == ["22:22:22:22:22:22"]
    assert bluetooth.scan_targets(paired, skip=["22:22:22:22:22:22"]) == []
    unknown = [("11:11:11:11:11:11", "A"), ("22:22:22:22:22:22", "B", None)]
    assert bluetooth.scan_targets(unknown) == ["11:11:11:11:11:11", "22:22:22:22:22:22"]


def test_phone_class_of_device() -> None:
    assert bluetooth.is_phone_class(0x5A020C)  # smartphone
    assert not bluetooth.is_phone_class(0x240404)  # headphones
    assert not bluetooth.is_phone_class(0x2A010C)  # laptop


def test_scan_reports_bridges_and_reasons() -> None:
    def opener(address, device_id, local_port, on_closed=None):
        if address.startswith("22"):
            left, right = socket.socketpair()
            Bridge(right, "phone-id", 1, odd=False).start()
            bridge = Bridge(left, device_id, local_port).start()
            bridge.wait_hello(5)
            return bridge
        raise OSError(10060, "timeout")

    paired = [("22:22:22:22:22:22", "S24", True), ("33:33:33:33:33:33", "Pixel", True)]
    found, problems = bluetooth.scan("pc-id", 1, paired, opener=opener)
    assert [(mac, bridge.remote_id) for mac, bridge in found] == [("22:22:22:22:22:22", "phone-id")]
    assert "svarede ikke" in problems["33:33:33:33:33:33"]
    for _mac, bridge in found:
        bridge.close()


def test_describe_windows_errors() -> None:
    assert "Tillad forbindelse via Bluetooth" in bluetooth.describe(OSError(10108, "x"))
    assert "slået fra på PC'en" in bluetooth.describe(OSError(10050, "x"))
    assert bluetooth.describe(ConnectionError("Ingen h4xtor share")) == "Ingen h4xtor share"
