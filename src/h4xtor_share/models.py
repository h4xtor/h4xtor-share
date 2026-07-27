from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TransportName = Literal["lan", "wifi", "wifi-direct", "bluetooth"]


@dataclass(slots=True)
class Peer:
    device_id: str
    name: str
    address: str
    port: int
    fingerprint: str
    platform: str
    transport: TransportName = "lan"

    @property
    def endpoint(self) -> str:
        return f"https://{self.address}:{self.port}"


@dataclass(slots=True)
class PairingPrompt:
    pairing_id: str
    peer_id: str
    peer_name: str
    code: str
    expires_at: float


@dataclass(slots=True)
class ClipboardReceived:
    peer_name: str
    text: str


@dataclass(slots=True)
class FileReceived:
    peer_name: str
    path: Path
    size: int


@dataclass(slots=True)
class TransferProgress:
    transfer_id: str
    file_name: str
    sent: int
    total: int
    direction: Literal["send", "receive"]

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 100.0
        return min(100.0, self.sent * 100.0 / self.total)
