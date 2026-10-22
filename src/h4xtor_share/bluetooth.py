"""Bluetooth bridge: carries the normal h4xtor share connections over one Bluetooth link.

Both ends run the same small multiplexer ("h4xtor-bt/1"). A connection that one side
makes to ``127.0.0.1:<bridge.port>`` becomes a stream over the link, and the other side
connects that stream to its own share server on ``127.0.0.1``. TLS, pinned certificates
and tokens are unchanged, so every feature works over Bluetooth without knowing about it.

The phone listens (Android ``listenUsingRfcommWithServiceRecord`` with ``SERVICE_UUID``);
the PC connects to a paired phone. Windows finds the RFCOMM channel through SDP by UUID;
Linux tries ``sdptool`` and else the usual channels. macOS has no RFCOMM sockets in Python.

Frame: type (1 byte) | stream id (4 bytes, big endian) | length (4 bytes) | payload.
The PC numbers its streams odd, the phone even, so both can open streams at once.
"""

from __future__ import annotations

import contextlib
import json
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor

SERVICE_UUID = "6f3b2a10-5c1e-4d8a-9f47-4834786f7231"
MAGIC = "h4xtor-bt/1"
HELLO, OPEN, DATA, CLOSE = 0, 1, 2, 3
HEADER = struct.Struct(">BII")
MAX_CHUNK = 32 * 1024
MAX_FRAME = 1024 * 1024
BULK = 16 * 1024  # a DATA frame this big is file data, not a ping
MAC_PATTERN = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
PHONE_CLASS = 2  # Bluetooth "major device class" for phones

# A paired device: (MAC, name) or (MAC, name, is_phone) where is_phone may be None (unknown).
PairedDevice = tuple


def encode(kind: int, stream: int, payload: bytes = b"") -> bytes:
    return HEADER.pack(kind, stream, len(payload)) + payload


def _read_exact(link: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = link.recv(size - len(data))
        if not chunk:
            raise ConnectionError("Bluetooth-forbindelsen blev afbrudt.")
        data += chunk
    return bytes(data)


class Bridge:
    """One end of the multiplexer over a connected stream socket (RFCOMM, or TCP in tests)."""

    def __init__(
        self,
        link: socket.socket,
        device_id: str,
        local_port: int,
        odd: bool = True,
        on_closed: Callable[[Bridge], None] | None = None,
    ) -> None:
        self.link = link
        self.device_id = device_id
        self.local_port = local_port
        self.on_closed = on_closed
        self.remote_id = ""
        self.opened = 0  # streams carried so far (both directions), handy for tests and status
        self.bulk_at = 0.0  # last time a full chunk went over the link (a file transfer)
        self._next_id = 1 if odd else 2
        self._streams: dict[int, socket.socket] = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._hello = threading.Event()
        self._closed = threading.Event()
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = int(self.listener.getsockname()[1])

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> Bridge:
        hello = json.dumps({"magic": MAGIC, "device_id": self.device_id}).encode()
        self._send(HELLO, 0, hello)
        threading.Thread(target=self._read_loop, name="h4x-bt-read", daemon=True).start()
        threading.Thread(target=self._accept_loop, name="h4x-bt-accept", daemon=True).start()
        return self

    def wait_hello(self, timeout: float) -> str:
        """The other side's device id; raises when it is not an h4xtor share bridge."""
        if not self._hello.wait(timeout) or not self.remote_id:
            self.close()
            raise ConnectionError("Ingen h4xtor share i den anden ende af Bluetooth-forbindelsen.")
        return self.remote_id

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    @property
    def busy(self) -> bool:
        """A file is on its way: closing the link now would break it (pings are tiny)."""
        return time.monotonic() - self.bulk_at < 15

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        for item in (self.link, self.listener):
            # shutdown() first: a thread blocked in recv()/accept() only wakes up that way.
            with contextlib.suppress(OSError):
                item.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                item.close()
        with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for stream in streams:
            with contextlib.suppress(OSError):
                stream.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                stream.close()
        self._hello.set()
        if self.on_closed is not None:
            self.on_closed(self)

    # -- link ------------------------------------------------------------------
    def _send(self, kind: int, stream: int, payload: bytes = b"") -> None:
        if len(payload) >= BULK:
            self.bulk_at = time.monotonic()
        with self._write_lock:
            self.link.sendall(encode(kind, stream, payload))

    def _read_loop(self) -> None:
        try:
            while not self._closed.is_set():
                kind, stream, length = HEADER.unpack(_read_exact(self.link, HEADER.size))
                if length > MAX_FRAME:
                    raise ConnectionError("Ugyldig Bluetooth-ramme.")
                payload = _read_exact(self.link, length) if length else b""
                self._handle(kind, stream, payload)
        except (OSError, ConnectionError, ValueError, struct.error):
            pass
        finally:
            self.close()

    def _handle(self, kind: int, stream: int, payload: bytes) -> None:
        if kind == HELLO:
            info = json.loads(payload.decode("utf-8"))
            if info.get("magic") != MAGIC:
                raise ValueError("not an h4xtor share bridge")
            self.remote_id = str(info.get("device_id") or "")[:64]
            self._hello.set()
        elif kind == OPEN:
            try:
                local = socket.create_connection(("127.0.0.1", self.local_port), timeout=5)
                local.settimeout(None)
            except OSError:
                self._send(CLOSE, stream)
                return
            self._attach(stream, local)
        elif kind == DATA:
            with self._lock:
                local = self._streams.get(stream)
            if len(payload) >= BULK:
                self.bulk_at = time.monotonic()
            if local is not None:
                # ponytail: no per-stream flow control; a stalled local reader stalls the link.
                try:
                    local.sendall(payload)
                except OSError:
                    self._drop(stream, tell_remote=True)
        elif kind == CLOSE:
            self._drop(stream, tell_remote=False)

    # -- streams ---------------------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._closed.is_set():
            try:
                local, _address = self.listener.accept()
            except OSError:
                return
            with self._lock:
                stream = self._next_id
                self._next_id += 2
            try:
                self._send(OPEN, stream)
            except OSError:
                local.close()
                self.close()
                return
            self._attach(stream, local)

    def _attach(self, stream: int, local: socket.socket) -> None:
        with self._lock:
            self._streams[stream] = local
            self.opened += 1
        threading.Thread(
            target=self._pump, args=(stream, local), name="h4x-bt-stream", daemon=True
        ).start()

    def _pump(self, stream: int, local: socket.socket) -> None:
        try:
            while True:
                chunk = local.recv(MAX_CHUNK)
                if not chunk:
                    break
                self._send(DATA, stream, chunk)
        except OSError:
            pass
        self._drop(stream, tell_remote=True)

    def _drop(self, stream: int, tell_remote: bool) -> None:
        with self._lock:
            local = self._streams.pop(stream, None)
        if local is None:
            return
        with contextlib.suppress(OSError):
            local.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            local.close()
        if tell_remote and not self._closed.is_set():
            with contextlib.suppress(OSError):
                self._send(CLOSE, stream)


# -- connecting to a phone -------------------------------------------------------
def supported() -> bool:
    return sys.platform == "win32" or sys.platform.startswith("linux")


def is_phone_class(cod: int) -> bool:
    """True when a Bluetooth "class of device" value says the device is a phone."""
    return (int(cod) >> 8) & 0x1F == PHONE_CLASS


def paired_devices() -> list[tuple[str, str, bool | None]]:
    """(MAC, name, is_phone) of the Bluetooth devices paired with this computer."""
    try:
        if sys.platform == "win32":
            return _paired_windows()
        if sys.platform.startswith("linux"):
            return _paired_linux()
    except OSError:
        pass
    return []


def _paired_windows() -> list[tuple[str, str, bool | None]]:
    import winreg

    devices = []
    path = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as root:
        index = 0
        while True:
            try:
                key_name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            name = ""
            phone: bool | None = None
            with contextlib.suppress(OSError), winreg.OpenKey(root, key_name) as key:
                raw, _kind = winreg.QueryValueEx(key, "Name")
                if isinstance(raw, bytes):
                    name = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
                elif isinstance(raw, str):
                    name = raw.split("\0", 1)[0]
                with contextlib.suppress(OSError, TypeError, ValueError):
                    cod, _kind = winreg.QueryValueEx(key, "COD")
                    phone = is_phone_class(int(cod))
            mac = ":".join(key_name[i : i + 2] for i in range(0, 12, 2)).upper()
            if MAC_PATTERN.match(mac):
                devices.append((mac, name, phone))
    return devices


def _paired_linux() -> list[tuple[str, str, bool | None]]:
    for command in (["bluetoothctl", "devices", "Paired"], ["bluetoothctl", "paired-devices"]):
        try:
            output = subprocess.run(
                command, capture_output=True, text=True, timeout=8, check=False
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        devices = []
        for line in output.splitlines():
            parts = line.strip().split(" ", 2)
            if len(parts) >= 2 and parts[0] == "Device" and MAC_PATTERN.match(parts[1].upper()):
                mac = parts[1].upper()
                devices.append((mac, parts[2] if len(parts) > 2 else "", _phone_linux(mac)))
        if devices:
            return devices
    return []


def _phone_linux(address: str) -> bool | None:
    try:
        output = subprocess.run(
            ["bluetoothctl", "info", address], capture_output=True, text=True, timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Class:\s*0x([0-9a-fA-F]+)", output)
    if match:
        return is_phone_class(int(match.group(1), 16))
    icon = re.search(r"Icon:\s*(\S+)", output)
    return icon.group(1) == "phone" if icon else None


def _phone_flag(device: PairedDevice) -> bool | None:
    return device[2] if len(device) > 2 else None


def candidates(
    paired: Iterable[PairedDevice],
    phone_name: str,
    remembered: str = "",
    everything: bool = False,
) -> list[str]:
    """MACs worth trying for a phone: the one that worked before, name matches, then phones.

    The h4xtor share name ("S24 Ultra") rarely equals the Bluetooth name ("Galaxy S24"),
    so every paired device that says it is a phone is tried too; the hello says who it is.
    ``everything`` adds the other paired devices as well (when the user asked explicitly);
    automatic attempts leave headphones and keyboards alone.
    """
    paired = list(paired)
    wanted = phone_name.casefold().strip()
    order: list[str] = []
    if remembered and MAC_PATTERN.match(remembered):
        order.append(remembered)
    for device in paired:
        mac, name = device[0], device[1].casefold().strip()
        if wanted and name and (wanted in name or name in wanted) and mac not in order:
            order.append(mac)
    order += [d[0] for d in paired if _phone_flag(d) and d[0] not in order]
    if everything:
        order += [d[0] for d in paired if d[0] not in order]
    return order


def scan_targets(paired: Iterable[PairedDevice], skip: Iterable[str] = ()) -> list[str]:
    """MACs to look for h4xtor share on: the paired phones (all devices when none says)."""
    paired = [d for d in paired if d[0] not in set(skip)]
    phones = [d[0] for d in paired if _phone_flag(d)]
    if phones:
        return phones
    # No class info at all (older Windows, plain Linux): try whatever is not known as non-phone.
    return [d[0] for d in paired if _phone_flag(d) is None]


def _sockets_for(address: str) -> Iterator[socket.socket]:
    """Connected RFCOMM sockets to *address* that may be the h4xtor share service."""
    if sys.platform == "win32":
        yield _connect_windows(address)
        return
    if not sys.platform.startswith("linux"):
        raise OSError("Bluetooth kræver Windows eller Linux.")
    channels = _sdp_channels_linux(address) or list(range(1, 31))
    for channel in channels:
        link = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        try:
            link.settimeout(8)
            link.connect((address, channel))
            link.settimeout(None)
        except OSError:
            link.close()
            continue
        yield link


def _sdp_channels_linux(address: str) -> list[int]:
    try:
        output = subprocess.run(
            ["sdptool", "search", "--bdaddr", address, SERVICE_UUID],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(value) for value in re.findall(r"Channel:\s*(\d+)", output)]


def windows_sockaddr(address: str) -> bytes:
    """SOCKADDR_BTH (packed, 30 bytes) that makes Winsock look the channel up by UUID."""
    bt_addr = int(address.replace(":", ""), 16)
    # addressFamily AF_BTH=32, btAddr, serviceClassId (GUID, little endian), port 0 = use SDP
    return struct.pack("<HQ16sI", 32, bt_addr, uuid.UUID(SERVICE_UUID).bytes_le, 0)


def _connect_windows(address: str) -> socket.socket:
    import ctypes

    link = socket.socket(32, socket.SOCK_STREAM, 3)  # AF_BTH, BTHPROTO_RFCOMM
    ws2 = ctypes.WinDLL("ws2_32")
    ws2.connect.argtypes = [ctypes.c_size_t, ctypes.c_char_p, ctypes.c_int]
    raw = windows_sockaddr(address)
    if ws2.connect(link.fileno(), raw, len(raw)) != 0:
        code = ws2.WSAGetLastError()
        link.close()
        raise OSError(code, f"Bluetooth-forbindelsen til {address} mislykkedes (fejl {code}).")
    return link


WINDOWS_ERRORS = {
    10013: "Windows nægtede adgang til Bluetooth.",
    10049: "Telefonen er ikke tilgængelig over Bluetooth lige nu.",
    10050: "Bluetooth er slået fra på PC'en.",
    10051: "Bluetooth er slået fra på PC'en.",
    10060: "Telefonen svarede ikke (er den tændt, i nærheden og har Bluetooth slået til?).",
    10061: "Telefonen afviste forbindelsen.",
    10064: "Telefonen er ikke inden for rækkevidde eller har Bluetooth slået fra.",
    10065: "Telefonen er ikke inden for rækkevidde eller har Bluetooth slået fra.",
    10108: "h4xtor share lytter ikke på Bluetooth på telefonen. Slå 'Tillad forbindelse via "
    "Bluetooth' til i appen (fanen Del).",
}


def describe(error: BaseException) -> str:
    """A short Danish explanation of a failed Bluetooth attempt."""
    code = getattr(error, "errno", None)
    if isinstance(code, int) and code in WINDOWS_ERRORS:
        return WINDOWS_ERRORS[code]
    text = str(error).strip()
    return text or "Ukendt Bluetooth-fejl."


def open_bridge(
    address: str,
    device_id: str,
    local_port: int,
    expected_id: str | None = None,
    on_closed: Callable[[Bridge], None] | None = None,
) -> Bridge:
    """Connect to the phone at *address* and return a running bridge (PC side, odd ids)."""
    last: Exception = OSError(f"Ingen h4xtor share på {address}.")
    for link in _sockets_for(address):
        bridge = Bridge(link, device_id, local_port, odd=True, on_closed=on_closed).start()
        try:
            remote = bridge.wait_hello(8)
        except ConnectionError as error:
            last = error
            continue
        if expected_id and remote != expected_id:
            bridge.close()
            last = ConnectionError("Bluetooth-enheden er en anden h4xtor share-enhed.")
            continue
        return bridge
    raise last


def scan(
    device_id: str,
    local_port: int,
    paired: Iterable[PairedDevice] | None = None,
    skip: Iterable[str] = (),
    on_closed: Callable[[Bridge], None] | None = None,
    opener: Callable[..., Bridge] | None = None,
) -> tuple[list[tuple[str, Bridge]], dict[str, str]]:
    """Look for h4xtor share on every paired phone at once.

    Returns the bridges that answered (MAC, bridge) and, per MAC that did not, why not.
    """
    opener = opener or open_bridge
    devices = list(paired_devices() if paired is None else paired)
    targets = scan_targets(devices, skip)
    found: list[tuple[str, Bridge]] = []
    problems: dict[str, str] = {}
    if not targets:
        return found, problems

    def one(address: str) -> None:
        try:
            found.append((address, opener(address, device_id, local_port, on_closed=on_closed)))
        except (OSError, ConnectionError) as error:
            problems[address] = describe(error)

    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        list(pool.map(one, targets))
    return found, problems
