from __future__ import annotations

import json
import platform
import socket
import uuid
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_downloads_dir

APP_NAME = "h4xtor-share"
DEFAULT_PORT = 47474


class Config:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(user_config_dir(APP_NAME)) / "config.json"
        self.data: dict[str, Any] = {
            "device_id": uuid.uuid4().hex,
            "device_name": socket.gethostname(),
            "port": DEFAULT_PORT,
            "incoming_directory": str(Path(user_downloads_dir()) / APP_NAME),
            "trusted_peers": {},
            "platform": platform.system().lower(),
            "apply_received_clipboard": True,
        }
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(loaded, dict):
            self.data.update(loaded)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @property
    def device_id(self) -> str:
        return str(self.data["device_id"])

    @property
    def device_name(self) -> str:
        return str(self.data["device_name"])

    @device_name.setter
    def device_name(self, value: str) -> None:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Device name cannot be empty.")
        self.data["device_name"] = normalized[:80]
        self.save()

    @property
    def port(self) -> int:
        return int(self.data["port"])

    @property
    def platform_name(self) -> str:
        return str(self.data["platform"])

    @property
    def incoming_directory(self) -> Path:
        return Path(str(self.data["incoming_directory"])).expanduser()

    @incoming_directory.setter
    def incoming_directory(self, value: Path) -> None:
        self.data["incoming_directory"] = str(value.expanduser().resolve())
        self.save()

    @property
    def apply_received_clipboard(self) -> bool:
        return bool(self.data.get("apply_received_clipboard", True))
    @apply_received_clipboard.setter
    def apply_received_clipboard(self, value: bool) -> None:
        self.data["apply_received_clipboard"] = bool(value)
        self.save()

    @property
    def history_path(self) -> Path:
        return self.path.parent / "history.json"

    @property
    def clipboard_sync_enabled(self) -> bool:
        return bool(self.data.get("clipboard_sync", True))

    @clipboard_sync_enabled.setter
    def clipboard_sync_enabled(self, value: bool) -> None:
        self.data["clipboard_sync"] = bool(value)
        self.save()

    def trust_outbound_peer(
        self,
        peer_id: str,
        token: str,
        fingerprint: str,
        name: str,
    ) -> None:
        trusted = self.data.setdefault("trusted_peers", {})
        entry = trusted.setdefault(peer_id, {})
        entry.update(
            {
                "name": name,
                "outbound_token": token,
                "fingerprint": fingerprint,
            }
        )
        self.save()

    def trust_inbound_peer(self, peer_id: str, token: str, name: str) -> None:
        trusted = self.data.setdefault("trusted_peers", {})
        entry = trusted.setdefault(peer_id, {})
        entry.update(
            {
                "name": name,
                "inbound_token": token,
            }
        )
        self.save()

    def outbound_credentials(self, peer_id: str) -> tuple[str, str] | None:
        entry = self.data.get("trusted_peers", {}).get(peer_id)
        if not isinstance(entry, dict):
            return None
        token = entry.get("outbound_token")
        fingerprint = entry.get("fingerprint")
        if not isinstance(token, str) or not isinstance(fingerprint, str):
            return None
        return token, fingerprint

    def validate_inbound_token(self, peer_id: str, token: str) -> bool:
        entry = self.data.get("trusted_peers", {}).get(peer_id)
        return isinstance(entry, dict) and entry.get("inbound_token") == token
