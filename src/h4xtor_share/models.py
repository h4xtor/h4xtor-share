from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TransportName = Literal["lan", "wifi", "wifi-direct", "bluetooth"]

#: Capabilities this desktop build advertises over mDNS, UDP and ``/info``.
DESKTOP_CAPABILITIES: tuple[str, ...] = (
    "clipboard",
    "files",
    "resume",
    "folders",
    "links",
    "mutual-pair",
    "qr-pair",
    "wifi-direct-join",
    "unpair",
)


@dataclass(slots=True)
class Peer:
    device_id: str
    name: str
    address: str
    port: int
    fingerprint: str
    platform: str
    transport: TransportName = "lan"
    capabilities: tuple[str, ...] = ()

    @property
    def endpoint(self) -> str:
        return f"https://{self.address}:{self.port}"

    @property
    def supports_folders(self) -> bool:
        return "folders" in self.capabilities

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(slots=True)
class PairingPrompt:
    pairing_id: str
    peer_id: str
    peer_name: str
    code: str
    expires_at: float


@dataclass(slots=True)
class ClipboardReceived:
    peer_id: str
    peer_name: str
    text: str


@dataclass(slots=True)
class FileReceived:
    peer_id: str
    peer_name: str
    path: Path
    size: int
    transfer_id: str = ""


@dataclass(slots=True)
class FolderReceived:
    peer_id: str
    peer_name: str
    path: Path
    size: int
    transfer_id: str = ""


@dataclass(slots=True)
class TransferProgress:
    transfer_id: str
    file_name: str
    sent: int
    total: int
    direction: Literal["send", "receive"]
    peer_name: str = ""

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 100.0
        return min(100.0, self.sent * 100.0 / self.total)


@dataclass(slots=True)
class PeerStatus:
    device_id: str
    online: bool
    rtt_ms: float | None


@dataclass(slots=True)
class PeerPaired:
    """A remote device completed pairing with this device (both directions)."""

    peer: Peer
    mutual: bool


@dataclass(slots=True)
class PeerForgotten:
    peer_id: str
    peer_name: str


@dataclass(slots=True)
class LinkReceived:
    peer_id: str
    peer_name: str
    url: str


@dataclass(slots=True)
class WifiDirectOffer:
    peer_id: str
    peer_name: str
    ssid: str
    passphrase: str
    owner_address: str
    port: int


@dataclass(slots=True)
class FileOpenRequested:
    path: str


def signal_bars(rtt_ms: float | None) -> str:
    """Map round-trip latency to a 4-level signal indicator.

    ``rtt_ms=None`` yields the empty glyph for an unreachable peer.
    """
    if rtt_ms is None:
        return ""
    if rtt_ms < 15:
        return "▂▄▆█"
    if rtt_ms < 40:
        return "▂▄▆"
    if rtt_ms < 100:
        return "▂▄"
    return "▂"
