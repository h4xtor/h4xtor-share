"""QR pairing invites.

A device that wants to be paired shows a QR code with an ``h4xtor://pair``
URI. The URI carries everything the scanning device needs to pair instantly
and securely:

* the device id and name,
* every local IPv4 address and the TCP port,
* the SHA-256 certificate fingerprint, so TLS is pinned from the first byte,
* a short-lived one-time secret that replaces the six-digit code.

The same format is produced and parsed by the Android app.
"""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
from dataclasses import dataclass

SCHEME = "h4xtor"
INVITE_VERSION = "1"
_DEVICE_ID = re.compile(r"^[a-f0-9]{32}$")
_FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class PairingInvite:
    device_id: str
    name: str
    fingerprint: str
    port: int
    addresses: tuple[str, ...]
    secret: str
    platform: str = "unknown"

    def to_uri(self) -> str:
        query = urllib.parse.urlencode(
            {
                "v": INVITE_VERSION,
                "id": self.device_id,
                "n": self.name,
                "fp": self.fingerprint,
                "p": str(self.port),
                "a": ",".join(self.addresses),
                "s": self.secret,
                "pl": self.platform,
            },
            quote_via=urllib.parse.quote,
        )
        return f"{SCHEME}://pair?{query}"


def parse_invite(uri: str) -> PairingInvite:
    """Parse and validate an ``h4xtor://pair`` URI. Raises ``ValueError``."""
    parsed = urllib.parse.urlsplit(uri.strip())
    if parsed.scheme.lower() != SCHEME or parsed.netloc.lower() != "pair":
        raise ValueError("Not an h4xtor-share pairing code.")
    values = {
        key: items[0]
        for key, items in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()
    }
    if values.get("v") != INVITE_VERSION:
        raise ValueError("Unsupported pairing code version.")
    device_id = values.get("id", "")
    fingerprint = values.get("fp", "").lower()
    secret = values.get("s", "")
    if not _DEVICE_ID.fullmatch(device_id):
        raise ValueError("Pairing code has an invalid device id.")
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("Pairing code has an invalid fingerprint.")
    if not 16 <= len(secret) <= 128:
        raise ValueError("Pairing code has an invalid secret.")
    try:
        port = int(values.get("p", ""))
    except ValueError as error:
        raise ValueError("Pairing code has an invalid port.") from error
    if not 0 < port < 65536:
        raise ValueError("Pairing code has an invalid port.")
    addresses: list[str] = []
    for raw in values.get("a", "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            address = ipaddress.IPv4Address(raw)
        except ValueError:
            continue
        addresses.append(str(address))
    if not addresses:
        raise ValueError("Pairing code has no reachable address.")
    return PairingInvite(
        device_id=device_id,
        name=values.get("n", "Device")[:80] or "Device",
        fingerprint=fingerprint,
        port=port,
        addresses=tuple(addresses),
        secret=secret,
        platform=values.get("pl", "unknown")[:32] or "unknown",
    )


def qr_matrix(text: str) -> list[list[bool]]:
    """Return the QR module matrix (True = dark) for *text*, quiet zone excluded."""
    import segno

    code = segno.make_qr(text, error="l")
    return [[bool(module) for module in row] for row in code.matrix]
