"""Wi-Fi + 5G: spread internet connections over every link at once (like net-merge).

The PC runs a small proxy on 127.0.0.1 (HTTP and SOCKS5 on one port) and points the
system proxy at it through a PAC file. Every new connection goes to one link:

* this PC's own network adapters (Wi-Fi, Ethernet, a USB-tethered phone …), bound by
  their source address;
* a paired phone on the same Wi-Fi that shares its mobile data: the PC opens a pinned
  TLS connection to the phone's h4xtor share server and asks it to ``CONNECT`` out over 5G.

Honest limits: one connection always uses one link, so a single download is not faster;
web pages, apps and parallel downloads (many connections) are. If the app dies, the PAC
file is gone and browsers fall back to a direct connection, so the internet never breaks.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import socket
import ssl
import struct
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import ifaddr

NETMERGE_PORT_OFFSET = 6
PROBE_HOST = "connectivitycheck.gstatic.com"
PROBE_INTERVAL = 20.0
CONNECT_TIMEOUT = 10.0
MAX_HEAD = 64 * 1024
CHUNK = 64 * 1024
DEFAULT_RATE = 2_000_000.0  # bytes/s guess until a link has moved real data
SPEED_WINDOW = 3.0  # seconds of samples kept for the live speed

PAC = """function FindProxyForURL(url, host) {
  if (isPlainHostName(host) || host == "localhost" || shExpMatch(host, "*.local")) return "DIRECT";
  if (/^[0-9.]+$/.test(host) && (isInNet(host, "10.0.0.0", "255.0.0.0") ||
      isInNet(host, "172.16.0.0", "255.240.0.0") || isInNet(host, "192.168.0.0", "255.255.0.0") ||
      isInNet(host, "127.0.0.0", "255.0.0.0") || isInNet(host, "169.254.0.0", "255.255.0.0")))
    return "DIRECT";
  return "PROXY 127.0.0.1:%d; DIRECT";
}
"""


@dataclass
class PhoneRoute:
    """How to reach a phone that shares its mobile data (from the pairing)."""

    address: str
    port: int
    fingerprint: str
    headers: dict[str, str]
    network: str = ""  # what the phone calls its mobile data, e.g. "5G"


@dataclass
class Link:
    key: str
    name: str
    kind: str  # "pc" | "phone"
    bind: str = ""
    phone: PhoneRoute | None = None
    healthy: bool = False
    latency: float | None = None
    rate: float = DEFAULT_RATE
    active: int = 0
    connections: int = 0
    received: int = 0
    sent: int = 0
    failures: int = 0
    _window: deque[tuple[float, int]] = field(default_factory=deque, repr=False)

    @property
    def score(self) -> float:
        """Faster links get more connections; busy links get fewer."""
        return self.rate / (self.active + 1)

    def count(self, size: int) -> None:
        self.received += size
        now = time.monotonic()
        self._window.append((now, size))
        # Trimmed here, not only by speed(): nobody reads it while the page is closed.
        while self._window[0][0] < now - SPEED_WINDOW:
            self._window.popleft()

    def speed(self, seconds: float = SPEED_WINDOW) -> float:
        """Bytes per second over the last few seconds (for the live display)."""
        horizon = time.monotonic() - seconds
        samples = tuple(self._window)  # one step: the proxy's thread appends while Tk reads
        return sum(size for at, size in samples if at >= horizon) / seconds


def adapter_addresses() -> list[tuple[str, str]]:
    """(adapter name, IPv4) for every usable local adapter."""
    found: list[tuple[str, str]] = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if not isinstance(ip.ip, str):
                continue
            parsed = ipaddress.ip_address(ip.ip)
            if parsed.is_loopback or parsed.is_link_local:
                continue
            found.append((str(adapter.nice_name or adapter.name), ip.ip))
    return found


def _fingerprint_ok(writer: asyncio.StreamWriter, expected: str) -> bool:
    ssl_object = writer.get_extra_info("ssl_object")
    der = ssl_object.getpeercert(binary_form=True) if ssl_object else None
    return bool(der) and hashlib.sha256(der).hexdigest() == expected.lower().replace(":", "")


def _client_ssl() -> ssl.SSLContext:
    # The phone's certificate is self-signed; it is pinned by fingerprint after the handshake.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def _read_head(reader: asyncio.StreamReader) -> bytes:
    try:
        return await reader.readuntil(b"\r\n\r\n")
    except asyncio.LimitOverrunError as error:
        raise ValueError("Request head too large") from error


def parse_target(text: str, default_port: int) -> tuple[str, int]:
    """'host:port' or '[v6]:port' → (host, port), with a port range check."""
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port_text = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, port_text = text.rpartition(":") if text.count(":") == 1 else (text, "", "")
    port = int(port_text) if port_text else default_port
    if not host or not 0 < port < 65536:
        raise ValueError(f"Bad target {text!r}")
    return host, port


def rewrite_http_request(head: bytes) -> tuple[str, int, bytes]:
    """Absolute-URI proxy request → (host, port, origin-form head with Connection: close)."""
    lines = head.decode("latin-1").split("\r\n")
    method, uri, version = lines[0].split(" ", 2)
    parts = urlsplit(uri)
    if parts.scheme != "http" or not parts.hostname:
        raise ValueError("Only http:// URLs can be proxied without CONNECT")
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    kept = [
        line
        for line in lines[1:]
        if line
        and line.split(":", 1)[0].strip().lower()
        not in {"proxy-connection", "proxy-authorization", "connection", "keep-alive"}
    ]
    # shortcut: one request per proxied connection (Connection: close); fine because most
    # traffic is HTTPS through CONNECT, upgrade to keep-alive parsing if plain HTTP matters.
    rebuilt = "\r\n".join([f"{method} {path} {version}", *kept, "Connection: close", "", ""])
    return parts.hostname, parts.port or 80, rebuilt.encode("latin-1")


class NetMerge:
    def __init__(
        self,
        port: int,
        *,
        host: str = "127.0.0.1",
        probe: tuple[str, int] = (PROBE_HOST, 80),
        adapters: Callable[[], list[tuple[str, str]]] = adapter_addresses,
    ) -> None:
        self.port = port
        self.host = host
        self.probe_target = probe
        self.adapters = adapters
        self.links: dict[str, Link] = {}
        self.phone_routes: dict[str, tuple[str, PhoneRoute]] = {}
        self._server: asyncio.base_events.Server | None = None
        self._prober: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def pac_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/proxy.pac"

    # ----------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._serve, self.host, self.port, limit=MAX_HEAD)
        self.refresh_links()
        self._prober = asyncio.create_task(self._probe_loop())

    async def stop(self) -> None:
        if self._prober is not None:
            self._prober.cancel()
            self._prober = None
        if self._server is not None:
            self._server.close()
            self._server = None
        for task in list(self._tasks):
            task.cancel()

    # --------------------------------------------------------------------- links
    def set_phone(self, device_id: str, name: str, route: PhoneRoute | None) -> None:
        """Add, update or (route=None) remove a phone that shares its mobile data."""
        if route is None:
            self.phone_routes.pop(device_id, None)
        else:
            self.phone_routes[device_id] = (name, route)
        self.refresh_links()

    def refresh_links(self) -> None:
        wanted: dict[str, Link] = {}
        for name, address in self.adapters():
            key = f"pc:{address}"
            wanted[key] = self.links.get(key) or Link(key, name, "pc", bind=address)
            wanted[key].name = name
        for device_id, (name, route) in self.phone_routes.items():
            key = f"phone:{device_id}"
            link = self.links.get(key) or Link(key, name, "phone")
            link.name, link.phone = name, route
            wanted[key] = link
        self.links = wanted

    def ranked(self) -> list[Link]:
        return sorted(
            (link for link in self.links.values() if link.healthy),
            key=lambda link: link.score,
            reverse=True,
        )

    # ------------------------------------------------------------------ dialling
    async def open_via(
        self, link: Link | None, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """TCP stream to host:port through one link (None = the system's default route)."""
        if link is None:
            return await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT)
        if link.phone is None:
            return await asyncio.wait_for(
                asyncio.open_connection(host, port, local_addr=(link.bind, 0)), CONNECT_TIMEOUT
            )
        route = link.phone
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(route.address, route.port, ssl=_client_ssl()),
            CONNECT_TIMEOUT,
        )
        try:
            if not _fingerprint_ok(writer, route.fingerprint):
                raise ConnectionError("The phone's certificate does not match the pairing")
            target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            extra = "".join(f"{k}: {v}\r\n" for k, v in route.headers.items())
            writer.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n{extra}\r\n".encode())
            await writer.drain()
            head = await asyncio.wait_for(_read_head(reader), CONNECT_TIMEOUT)
            status = head.split(b"\r\n", 1)[0].split(b" ")
            if len(status) < 2 or status[1] != b"200":
                raise ConnectionError(head.decode("latin-1", "replace").strip())
        except BaseException:
            writer.close()
            raise
        return reader, writer

    async def dial(
        self, host: str, port: int
    ) -> tuple[Link | None, asyncio.StreamReader, asyncio.StreamWriter]:
        """Best link first; on failure the next one; last resort the default route."""
        for link in self.ranked()[:2]:
            link.active += 1
            try:
                reader, writer = await self.open_via(link, host, port)
            except (OSError, ValueError):  # timeouts, refusals and TLS errors are OSErrors
                link.active -= 1
                link.failures += 1
                continue
            link.connections += 1
            return link, reader, writer
        reader, writer = await self.open_via(None, host, port)
        return None, reader, writer

    # ------------------------------------------------------------------- probing
    async def probe(self, link: Link) -> None:
        host, port = self.probe_target
        started = time.monotonic()
        try:
            reader, writer = await self.open_via(link, host, port)
            try:
                request = f"GET /generate_204 HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
                writer.write(request.encode())
                await writer.drain()
                status = await asyncio.wait_for(reader.readline(), CONNECT_TIMEOUT)
            finally:
                writer.close()
            link.healthy = status.split(b" ")[1:2] in ([b"204"], [b"200"])
            link.latency = time.monotonic() - started if link.healthy else None
        except (OSError, ValueError):  # timeouts, refusals and TLS errors are OSErrors
            link.healthy, link.latency = False, None

    async def probe_all(self) -> None:
        self.refresh_links()
        await asyncio.gather(*(self.probe(link) for link in list(self.links.values())))

    async def _probe_loop(self) -> None:
        while True:
            with contextlib.suppress(Exception):
                await self.probe_all()
            await asyncio.sleep(PROBE_INTERVAL)

    # ------------------------------------------------------------------ serving
    def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(self._client(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            first = await asyncio.wait_for(reader.readexactly(1), 30)
            if first == b"\x05":
                await self._socks(reader, writer)
            else:
                await self._http(first + await _read_head(reader), reader, writer)
        except (OSError, asyncio.IncompleteReadError, ValueError):
            pass
        finally:
            writer.close()

    async def _http(
        self, head: bytes, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        method, target = request_line.split(" ")[:2]
        if method == "GET" and target.startswith("/proxy.pac"):
            body = (PAC % self.port).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ns-proxy-autoconfig\r\n"
                + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
            return
        if method == "CONNECT":
            host, port = parse_target(target, 443)
            first_bytes = b""
        else:
            host, port, first_bytes = rewrite_http_request(head)
        try:
            link, up_reader, up_writer = await self.dial(host, port)
        except (OSError, ValueError):
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        if method == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:
            up_writer.write(first_bytes)
        await self._splice(link, reader, writer, up_reader, up_writer)

    async def _socks(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        methods = await reader.readexactly((await reader.readexactly(1))[0])
        if 0 not in methods:
            writer.write(b"\x05\xff")
            return
        writer.write(b"\x05\x00")
        version, command, _, address_type = await reader.readexactly(4)
        if address_type == 1:
            host = socket.inet_ntoa(await reader.readexactly(4))
        elif address_type == 3:
            host = (await reader.readexactly((await reader.readexactly(1))[0])).decode("idna")
        elif address_type == 4:
            host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
        else:
            raise ValueError("Unknown SOCKS address type")
        (port,) = struct.unpack("!H", await reader.readexactly(2))
        if version != 5 or command != 1:  # only CONNECT; UDP stays on the default route
            writer.write(b"\x05\x07\x00\x01" + bytes(6))
            return
        try:
            link, up_reader, up_writer = await self.dial(host, port)
        except (OSError, ValueError):
            writer.write(b"\x05\x05\x00\x01" + bytes(6))
            return
        writer.write(b"\x05\x00\x00\x01" + bytes(6))
        await self._splice(link, reader, writer, up_reader, up_writer)

    async def _splice(
        self,
        link: Link | None,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        up_reader: asyncio.StreamReader,
        up_writer: asyncio.StreamWriter,
    ) -> None:
        started = time.monotonic()
        moved = [0, 0.0]  # downstream bytes, time of the last downstream byte

        async def pump(
            source: asyncio.StreamReader, sink: asyncio.StreamWriter, down: bool
        ) -> None:
            try:
                while chunk := await source.read(CHUNK):
                    sink.write(chunk)
                    await sink.drain()
                    if link is not None:
                        if down:
                            link.count(len(chunk))
                            moved[0] += len(chunk)
                            moved[1] = time.monotonic()
                        else:
                            link.sent += len(chunk)
            except (OSError, asyncio.IncompleteReadError):
                pass
            finally:
                with contextlib.suppress(OSError):
                    if sink.can_write_eof():
                        sink.write_eof()
                    elif not down:
                        # TLS to a phone cannot half-close: the client is gone, so end the
                        # tunnel (an idle server would otherwise hold it, and the link's count).
                        sink.close()

        upload = asyncio.create_task(pump(reader, up_writer, False))
        try:
            await pump(up_reader, writer, True)
        finally:
            # The server is done: TLS to a phone cannot half-close, so stop the upload side too.
            upload.cancel()
            up_writer.close()
            if link is not None:
                link.active -= 1
                if moved[0] >= 512 * 1024:
                    # Learn each link's real speed from big transfers (moving average).
                    busy = max(moved[1] - started, 0.001)
                    link.rate = 0.7 * link.rate + 0.3 * (moved[0] / busy)
