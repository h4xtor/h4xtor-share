"""JSON-backed history of transfers, links and known devices.

The store lives next to ``config.json`` and keeps bounded ring-buffers of
sent/received entries plus a per-device metadata log with connection
timestamps.  All writes are synchronous and atomic (write-then-rename), the
same pattern the ``Config`` class already uses.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any

from h4xtor_share.models import Peer

HISTORY_FILE_NAME = "history.json"
MAX_ENTRIES = 500


def is_link(text: str) -> bool:
    """True when *text* is a single URL with an http(s) scheme."""
    value = text.strip()
    try:
        scheme = urllib.parse.urlsplit(value).scheme
    except ValueError:
        return False
    return scheme in {"http", "https"} and " " not in value


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.data: dict[str, Any] = {"sent": [], "received": [], "devices": {}}
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(loaded, dict):
            for key in ("sent", "received", "devices"):
                if key in loaded:
                    self.data[key] = loaded[key]

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _append(self, key: str, entry: dict[str, Any]) -> None:
        bucket = self.data.setdefault(key, [])
        bucket.append(entry)
        del bucket[:-MAX_ENTRIES]
        self._save()

    @staticmethod
    def _entry(peer: Peer, kind: str, text: str, size: int, path: str) -> dict[str, Any]:
        return {
            "ts": _now(),
            "peer": peer.name,
            "peer_id": peer.device_id,
            "ip": peer.address,
            "kind": kind,
            "text": text[:1000],
            "size": size,
            "path": path,
        }

    def record_sent_file(self, peer: Peer, name: str, size: int, path: str) -> None:
        self._append("sent", self._entry(peer, "file", name, size, path))

    def record_sent_text(self, peer: Peer, text: str) -> None:
        kind = "link" if is_link(text) else "clipboard"
        self._append("sent", self._entry(peer, kind, text, len(text), ""))

    def record_received_file(self, peer: Peer, name: str, size: int, path: str) -> None:
        self._append("received", self._entry(peer, "file", name, size, path))

    def record_received_text(self, peer: Peer, text: str) -> None:
        kind = "link" if is_link(text) else "clipboard"
        self._append("received", self._entry(peer, kind, text, len(text), ""))

    def record_connection(
        self,
        peer: Peer,
        online: bool,
        rtt_ms: float | None = None,
    ) -> None:
        devices = self.data.setdefault("devices", {})
        entry = devices.setdefault(peer.device_id, {})
        changed = (
            entry.get("online") is not online
            and "first_seen" in entry
        )
        if "first_seen" not in entry:
            entry["first_seen"] = _now()
        entry.update(
            {
                "name": peer.name,
                "ip": peer.address,
                "os": peer.platform,
                "last_seen": _now(),
                "online": online,
                "connections": int(entry.get("connections", 0)) + (1 if changed else 0),
            }
        )
        if rtt_ms is not None:
            entry["last_rtt_ms"] = round(rtt_ms, 1)
        self._save()

    def sent(self) -> list[dict[str, Any]]:
        return list(reversed(self.data.get("sent", [])))

    def received(self) -> list[dict[str, Any]]:
        return list(reversed(self.data.get("received", [])))

    def devices(self) -> list[dict[str, Any]]:
        return sorted(
            self.data.get("devices", {}).values(),
            key=lambda entry: str(entry.get("last_seen", "")),
            reverse=True,
        )
