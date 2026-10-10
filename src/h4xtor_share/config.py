from __future__ import annotations

import json
import platform
import secrets
import socket
import uuid
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_downloads_dir

from h4xtor_share.models import Peer

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
            "known_peers": {},
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
    def gdrive_token_path(self) -> Path:
        return self.path.parent / "gdrive.token"

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
        if not isinstance(entry, dict):
            return False
        expected = entry.get("inbound_token")
        return isinstance(expected, str) and secrets.compare_digest(expected, token)

    def is_trusted(self, peer_id: str) -> bool:
        return self.outbound_credentials(peer_id) is not None

    def trusted_peer_ids(self) -> list[str]:
        return [
            peer_id
            for peer_id in self.data.get("trusted_peers", {})
            if self.outbound_credentials(peer_id) is not None
        ]

    def forget_peer(self, peer_id: str) -> None:
        self.data.get("trusted_peers", {}).pop(peer_id, None)
        self.data.get("known_peers", {}).pop(peer_id, None)
        self.save()

    def trust_both_ways(self, peer_id: str) -> bool:
        return self.is_trusted(peer_id)

    # -- known peers --------------------------------------------------------
    def remember_peer(self, peer: Peer) -> None:
        """Persist the last address of a trusted peer so it reconnects at startup."""
        known = self.data.setdefault("known_peers", {})
        entry = {
            "name": peer.name,
            "address": peer.address,
            "port": peer.port,
            "fingerprint": peer.fingerprint,
            "platform": peer.platform,
            "transport": peer.transport,
            "capabilities": list(peer.capabilities),
        }
        if known.get(peer.device_id) == entry:
            return
        known[peer.device_id] = entry
        self.save()

    def known_peers(self) -> list[Peer]:
        peers: list[Peer] = []
        for peer_id, entry in self.data.get("known_peers", {}).items():
            if not isinstance(entry, dict):
                continue
            try:
                peers.append(
                    Peer(
                        device_id=str(peer_id),
                        name=str(entry.get("name") or peer_id),
                        address=str(entry["address"]),
                        port=int(entry.get("port") or DEFAULT_PORT),
                        fingerprint=str(entry.get("fingerprint") or ""),
                        platform=str(entry.get("platform") or "unknown"),
                        transport=entry.get("transport") or "lan",
                        capabilities=tuple(
                            str(item) for item in entry.get("capabilities") or ()
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return peers

    # -- hidden (removed) devices ------------------------------------------
    def hidden_peers(self) -> set[str]:
        return {str(item) for item in self.data.get("hidden_peers", [])}

    def hide_peer(self, peer_id: str) -> None:
        hidden = self.hidden_peers()
        hidden.add(peer_id)
        self.data["hidden_peers"] = sorted(hidden)[-200:]
        self.save()

    def unhide_peer(self, peer_id: str) -> None:
        hidden = self.hidden_peers()
        if peer_id in hidden:
            hidden.discard(peer_id)
            self.data["hidden_peers"] = sorted(hidden)
            self.save()

    # -- preferences ---------------------------------------------------------
    def get_flag(self, key: str, default: bool) -> bool:
        return bool(self.data.get(key, default))

    def set_flag(self, key: str, value: bool) -> None:
        self.data[key] = bool(value)
        self.save()

    @property
    def open_links(self) -> bool:
        return self.get_flag("open_links", True)

    @open_links.setter
    def open_links(self, value: bool) -> None:
        self.set_flag("open_links", value)

    @property
    def theme(self) -> str:
        value = str(self.data.get("theme") or "system")
        return value if value in {"system", "light", "dark"} else "system"

    @theme.setter
    def theme(self, value: str) -> None:
        if value not in {"system", "light", "dark"}:
            raise ValueError("Unknown theme.")
        self.data["theme"] = value
        self.save()
