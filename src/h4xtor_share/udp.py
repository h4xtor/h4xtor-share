from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable

from h4xtor_share.config import Config
from h4xtor_share.discovery import local_ipv4_addresses
from h4xtor_share.models import Peer

ANNOUNCE_INTERVAL_SECONDS = 5.0
PROTOCOL_VERSION = 1
BROADCAST_ADDRESS = "255.255.255.255"


def encode_announcement(
    config: Config,
    fingerprint: str,
    capabilities: tuple[str, ...],
) -> bytes:
    payload = {
        "protocol": PROTOCOL_VERSION,
        "device_id": config.device_id,
        "name": config.device_name,
        "platform": config.platform_name,
        "port": config.port,
        "fingerprint": fingerprint,
        "capabilities": list(capabilities),
    }
    return json.dumps(payload).encode("utf-8")


def peer_from_announcement(payload: object, address: str) -> Peer:
    """Build a ``Peer`` from a parsed UDP announcement payload.

    Raises ``ValueError`` for malformed or incompatible announcements so the
    listener can ignore unrelated broadcast traffic.
    """
    if not isinstance(payload, dict):
        raise ValueError("Announcement is not an object.")
    if int(payload.get("protocol") or 0) != PROTOCOL_VERSION:
        raise ValueError("Unsupported h4xtor-share protocol.")
    device_id = str(payload.get("device_id") or "")
    if not device_id:
        raise ValueError("Announcement is missing a device id.")
    capabilities = payload.get("capabilities") or []
    return Peer(
        device_id=device_id,
        name=str(payload.get("name") or "Unknown device"),
        address=address,
        port=int(payload["port"]),
        fingerprint=str(payload.get("fingerprint") or ""),
        platform=str(payload.get("platform") or "unknown"),
        transport="lan",
        capabilities=tuple(str(capability) for capability in capabilities),
    )


class UdpDiscovery:
    """Zero-configuration UDP broadcast discovery.

    mDNS multicast is the primary discovery mechanism, but some networks
    filter multicast while still forwarding broadcast traffic. ``UdpDiscovery``
    periodically announces this device over UDP broadcast on the configured
    port and listens for announcements from peers, giving an automatic fallback
    that requires no user configuration.
    """

    def __init__(
        self,
        config: Config,
        fingerprint: str,
        capabilities: tuple[str, ...],
        peer_callback: Callable[[Peer], None],
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.fingerprint = fingerprint
        self.capabilities = capabilities
        self.peer_callback = peer_callback
        self.status_callback = status_callback
        self._stop_event = threading.Event()
        self._listener_thread: threading.Thread | None = None
        self._announcer_thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._listener_thread = threading.Thread(
            target=self._listen_loop,
            name="h4xtor-udp-listen",
            daemon=True,
        )
        self._announcer_thread = threading.Thread(
            target=self._announce_loop,
            name="h4xtor-udp-announce",
            daemon=True,
        )
        self._listener_thread.start()
        self._announcer_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._listener_thread:
            self._listener_thread.join(timeout=2)
        if self._announcer_thread:
            self._announcer_thread.join(timeout=2)
        self._listener_thread = None
        self._announcer_thread = None

    def _report(self, text: str) -> None:
        if self.status_callback:
            self.status_callback(text)

    def _listen_loop(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", self.config.port))
            sock.settimeout(0.5)
        except OSError as error:
            self._report(f"UDP discovery unavailable: {error}")
            return

        while not self._stop_event.is_set():
            try:
                data, address = sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                if not self._stop_event.is_set():
                    self._report("UDP discovery listener stopped unexpectedly.")
                break
            try:
                peer = peer_from_announcement(
                    json.loads(data.decode("utf-8")),
                    address[0],
                )
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if peer.device_id == self.config.device_id:
                continue
            self.peer_callback(peer)
        sock.close()

    def _announce_loop(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            return
        datagram = encode_announcement(self.config, self.fingerprint, self.capabilities)
        # The limited broadcast address covers the local subnet; unicasting to
        # each interface address is a fallback when broadcast is restricted.
        targets = [BROADCAST_ADDRESS, *local_ipv4_addresses()]
        while not self._stop_event.is_set():
            for target in targets:
                try:
                    sock.sendto(datagram, (target, self.config.port))
                except OSError:
                    continue
            self._stop_event.wait(ANNOUNCE_INTERVAL_SECONDS)
        sock.close()
