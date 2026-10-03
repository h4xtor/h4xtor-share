"""h4xtor share desktop app.

A calm, modern Tk interface around the peer-to-peer core: discover devices,
pair them with a QR code, drop files to send, push links and keep the
clipboard in sync. Networking runs on a private asyncio loop; the UI thread
only reads from a queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import platform
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
import webbrowser
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from tkinterdnd2 import DND_FILES, TkinterDnD

from h4xtor_share import __version__, integration, wifidirect
from h4xtor_share.client import PeerClient
from h4xtor_share.config import Config
from h4xtor_share.crypto import ensure_certificate, server_ssl_context
from h4xtor_share.discovery import DiscoveryService, local_ipv4_addresses
from h4xtor_share.history import HistoryStore, is_link
from h4xtor_share.local_api import LOCAL_API_PORT_OFFSET, LocalApi
from h4xtor_share.models import (
    DESKTOP_CAPABILITIES,
    ClipboardReceived,
    FileReceived,
    FolderReceived,
    LinkReceived,
    PairingPrompt,
    Peer,
    PeerForgotten,
    PeerPaired,
    PeerStatus,
    TransferProgress,
    WifiDirectOffer,
)
from h4xtor_share.openers import open_path, reveal_in_folder
from h4xtor_share.pairing import PairingInvite, parse_invite, qr_matrix
from h4xtor_share.scanner import scan_lan as scan_lan_peers
from h4xtor_share.server import ShareServer
from h4xtor_share.tray import TrayIcon
from h4xtor_share.udp import UdpDiscovery
from h4xtor_share.ui_kit import (
    Avatar,
    Button,
    Card,
    Modal,
    Monkey,
    ProgressBar,
    QrCanvas,
    ScrollFrame,
    SignalBars,
    Theme,
    Toast,
    Toggle,
    entry,
    round_rect,
    set_dark_titlebar,
)

APP_TITLE = "h4xtor share"
VERSION = __version__

HEALTH_INTERVAL_MS = 4000
CLIPBOARD_POLL_MS = 500
CLIPBOARD_SUPPRESS_SECONDS = 3.0
SEND_CONCURRENCY = 3
MAX_TRANSFER_ROWS = 80
QR_REFRESH_MS = 240_000

PLATFORM_LABELS = {
    "android": "Android",
    "windows": "Windows",
    "linux": "Linux",
    "darwin": "macOS",
    "macos": "macOS",
}
TRANSPORT_LABELS = {
    "lan": "Wi-Fi / LAN",
    "wifi": "Wi-Fi",
    "wifi-direct": "Wi-Fi Direct",
    "bluetooth": "Bluetooth",
}


def _format_bytes(value: float) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _format_speed(bytes_per_second: float) -> str:
    if bytes_per_second <= 0:
        return ""
    return f"{_format_bytes(bytes_per_second)}/s"


def _format_eta(seconds: float) -> str:
    if seconds < 1 or seconds > 86_400 * 2:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s tilbage"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {rest:02d} s tilbage"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} t {minutes} min tilbage"


def friendly_error(error: BaseException, peers: Any = ()) -> str:
    """Turn low-level network errors into a short, actionable Danish sentence."""
    import aiohttp

    def name_for(host: str) -> str:
        for peer in peers:
            if getattr(peer, "address", None) == host:
                return peer.name
        return host

    if isinstance(error, aiohttp.ServerFingerprintMismatch):
        return (
            f"{name_for(error.host)} har fået et nyt sikkerhedscertifikat "
            "(fx efter en opdatering). Forbind igen med QR-koden."
        )
    if isinstance(error, aiohttp.ClientConnectorError):
        return (
            f"Kan ikke nå {name_for(error.host)}. Tjek at h4xtor share er åben på enheden "
            "og at I er på samme Wi-Fi."
        )
    if isinstance(error, asyncio.TimeoutError | TimeoutError):
        return "Enheden svarede ikke i tide. Prøv igen."
    return str(error) or error.__class__.__name__


def is_newer_version(candidate: str, current: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        numbers = []
        for piece in value.strip().lstrip("vV").split("."):
            digits = "".join(ch for ch in piece if ch.isdigit())
            numbers.append(int(digits or 0))
        return tuple(numbers)

    try:
        return parts(candidate) > parts(current)
    except ValueError:
        return False


def _sorted_lan_addresses() -> list[str]:
    """Local IPv4 addresses, the most likely reachable ones first."""

    def rank(address: str) -> tuple[int, str]:
        ip = ipaddress.ip_address(address)
        if address.startswith("192.168.49."):
            return (0, address)  # Wi-Fi Direct
        if address.startswith("192.168."):
            return (1, address)
        if ip.is_private and not address.startswith("172.17."):
            return (2, address)
        return (3, address)

    return sorted(local_ipv4_addresses(), key=rank)


class AsyncRuntime:
    def __init__(self, result_queue: queue.Queue[tuple[str, Any]]) -> None:
        self.result_queue = result_queue
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coroutine: Any, success_tag: str) -> Future[Any]:
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)

        def finished(result: Future[Any]) -> None:
            if result.cancelled():
                self.result_queue.put(("cancelled", success_tag))
                return
            try:
                value = result.result()
            except asyncio.CancelledError:
                self.result_queue.put(("cancelled", success_tag))
            except Exception as error:
                self.result_queue.put(("error", error))
            else:
                self.result_queue.put((success_tag, value))

        future.add_done_callback(finished)
        return future

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self._cancel_pending_tasks)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)

    def _cancel_pending_tasks(self) -> None:
        for task in asyncio.all_tasks(self.loop):
            task.cancel()


@dataclass
class TransferState:
    transfer_id: str
    name: str
    direction: str
    peer_name: str
    total: int = 0
    sent: int = 0
    speed: float = 0.0
    last_time: float = field(default_factory=time.monotonic)
    last_sent: int = 0
    status: str = "active"  # active | done | failed | cancelled
    path: str = ""
    batch: str = ""


class DeviceCard:
    """One device row. Paired devices and devices merely found on the LAN look
    clearly different, and every row can be removed."""

    def __init__(self, app: H4xtorShareApp, parent: tk.Misc, peer: Peer) -> None:
        self.app = app
        self.peer = peer
        self.parent = parent
        self._mode = ""
        self.card: Card | None = None
        self.build()

    def build(self) -> None:
        app = self.app
        theme = app.theme
        c = theme.c
        px = theme.px
        paired = app.config_store.is_trusted(self.peer.device_id)
        self._mode = "paired" if paired else "lan"
        if self.card is not None:
            self.card.destroy()
        parent = app.paired_list if paired else app.lan_list
        self.card = Card(parent, theme, padding=12, radius=14)
        body = self.card.body
        body.grid_columnconfigure(1, weight=1)

        self.avatar = Avatar(body, theme, self.peer.platform, size=38)
        self.avatar.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, px(12)))
        self.name_label = tk.Label(
            body, text="", bg=c["card"], fg=c["text"], font=theme.font(11, "bold"), anchor="w"
        )
        self.name_label.grid(row=0, column=1, sticky="ew")
        meta = tk.Frame(body, bg=c["card"])
        meta.grid(row=1, column=1, sticky="ew", pady=(px(1), 0))
        self.dot = tk.Label(meta, text="●", bg=c["card"], fg=c["faint"], font=theme.font(8))
        self.dot.pack(side="left")
        self.meta_label = tk.Label(
            meta, text="", bg=c["card"], fg=c["muted"], font=theme.font(9), anchor="w"
        )
        self.meta_label.pack(side="left", padx=(px(5), 0))

        right = tk.Frame(body, bg=c["card"])
        right.grid(row=0, column=2, rowspan=2, sticky="e")
        self.signal = SignalBars(right, theme)
        self.signal.pack(side="left", padx=(0, px(12)))
        if paired:
            Button(
                right,
                theme,
                "Send filer",
                lambda: app.send_files(self.peer),
                kind="soft",
                size="sm",
                icon="↑",
            ).pack(side="left")
            self.menu_button = Button(
                right, theme, "", self.open_menu, kind="ghost", icon="⋯", size="sm", width=32
            )
            self.menu_button.pack(side="left", padx=(px(4), 0))
        else:
            Button(
                right,
                theme,
                "Forbind",
                lambda: app.pair_with_code(self.peer),
                kind="primary",
                size="sm",
            ).pack(side="left")
            self.menu_button = Button(
                right,
                theme,
                "",
                lambda: app.remove_device(self.peer),
                kind="ghost",
                icon="✕",
                size="sm",
                width=32,
            )
            self.menu_button.pack(side="left", padx=(px(4), 0))

        clickable = (self.card, body, self.name_label, meta, self.meta_label, self.avatar, self.dot)
        for widget in clickable:
            widget.bind("<Button-1>", lambda _e: self._clicked())
            widget.bind("<Button-3>", lambda _e: self.open_menu())
            widget.configure(cursor="hand2")
        self.update(self.peer)

    def _clicked(self) -> None:
        if self.app.config_store.is_trusted(self.peer.device_id):
            self.app.select_peer(self.peer.device_id)
        else:
            self.app.pair_with_code(self.peer)

    def update(self, peer: Peer) -> None:
        self.peer = peer
        app = self.app
        c = app.theme.c
        paired = app.config_store.is_trusted(peer.device_id)
        if ("paired" if paired else "lan") != self._mode:
            self.build()
            return
        status = app.peer_status.get(peer.device_id)
        online = status is not None and status.online
        selected = paired and app.selected_id == peer.device_id
        platform_label = PLATFORM_LABELS.get(peer.platform.lower(), peer.platform.title())
        transport = TRANSPORT_LABELS.get(peer.transport, peer.transport)
        self.name_label.configure(text=peer.name + ("   ✓ valgt" if selected else ""))
        if paired:
            state = "Online" if online else "Offline"
            self.dot.configure(fg=c["success"] if online else c["faint"])
            self.meta_label.configure(
                text=f"{state}  ·  {platform_label}  ·  {transport}  ·  {peer.address}"
            )
        else:
            self.dot.configure(fg=c["accent"] if online else c["faint"])
            self.meta_label.configure(
                text=f"Ikke forbundet  ·  fundet på {transport}  ·  {platform_label}  ·  "
                f"{peer.address}"
            )
        self.signal.set(status.rtt_ms if online and status is not None else None)
        assert self.card is not None
        self.card.set_colors(outline=c["accent"] if selected else c["border"])

    def open_menu(self) -> None:
        app = self.app
        menu = tk.Menu(app, tearoff=0)
        if app.config_store.is_trusted(self.peer.device_id):
            menu.add_command(label="Send filer…", command=lambda: app.send_files(self.peer))
            menu.add_command(label="Send mappe…", command=lambda: app.send_folder(self.peer))
            menu.add_command(
                label="Send tekst eller link…", command=lambda: app.compose_text(self.peer)
            )
            menu.add_command(
                label="Send udklipsholder", command=lambda: app.send_clipboard(self.peer)
            )
            menu.add_separator()
            menu.add_command(label="Fjern enhed…", command=lambda: app.confirm_remove(self.peer))
        else:
            menu.add_command(label="Forbind…", command=lambda: app.pair_with_code(self.peer))
            menu.add_separator()
            menu.add_command(label="Fjern fra listen", command=lambda: app.remove_device(self.peer))
        x = self.menu_button.winfo_rootx()
        y = self.menu_button.winfo_rooty() + self.menu_button.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def destroy(self) -> None:
        if self.card is not None:
            self.card.destroy()


class TransferRow:
    def __init__(self, app: H4xtorShareApp, parent: tk.Misc, state: TransferState) -> None:
        self.app = app
        self.state = state
        theme = app.theme
        c = theme.c
        self.card = Card(parent, theme, padding=14, radius=12)
        body = self.card.body
        body.grid_columnconfigure(1, weight=1)
        arrow = "↑" if state.direction == "send" else "↓"
        size = theme.px(38)
        self.icon = tk.Canvas(
            body, width=size, height=size, bg=c["card"], highlightthickness=0, bd=0
        )
        round_rect(
            self.icon,
            0,
            0,
            size,
            size,
            theme.px(10),
            fill=c["accent_soft"],
            outline=c["accent_soft"],
        )
        self.icon.create_text(
            size / 2, size / 2, text=arrow, fill=c["accent"], font=theme.font(13, "bold")
        )
        self.icon.grid(row=0, column=0, rowspan=3, sticky="w", padx=(0, theme.px(14)))
        self.name = tk.Label(
            body,
            text=state.name,
            bg=c["card"],
            fg=c["text"],
            font=theme.font(10, "bold"),
            anchor="w",
        )
        self.name.grid(row=0, column=1, sticky="ew")
        self.buttons = tk.Frame(body, bg=c["card"])
        self.buttons.grid(row=0, column=2, rowspan=3, sticky="e", padx=(theme.px(12), 0))
        self.bar = ProgressBar(body, theme)
        self.bar.grid(row=1, column=1, sticky="ew", pady=(theme.px(8), theme.px(6)))
        self.detail = tk.Label(
            body, text="", bg=c["card"], fg=c["muted"], font=theme.font(9), anchor="w"
        )
        self.detail.grid(row=2, column=1, sticky="ew")
        self._button_state = ""
        self.refresh()

    def refresh(self) -> None:
        state = self.state
        c = self.app.theme.c
        fraction = state.sent / state.total if state.total > 0 else 1.0
        direction = "Til" if state.direction == "send" else "Fra"
        parts = [f"{direction} {state.peer_name}"]
        if state.status == "active":
            parts.append(f"{fraction * 100:.0f}%")
            parts.append(f"{_format_bytes(state.sent)} af {_format_bytes(state.total)}")
            if state.speed > 0:
                parts.append(_format_speed(state.speed))
                eta = _format_eta((state.total - state.sent) / state.speed)
                if eta:
                    parts.append(eta)
            color = c["accent"]
        elif state.status == "done":
            parts.append(f"Færdig · {_format_bytes(state.total)}")
            color = c["success"]
            fraction = 1.0
        elif state.status == "cancelled":
            parts.append("Annulleret – kan genoptages")
            color = c["faint"]
        else:
            parts.append("Mislykkedes – prøv igen for at genoptage")
            color = c["danger"]
        self.bar.set(fraction, color)
        self.detail.configure(text="  ·  ".join(parts))

        wanted = state.status + (":path" if state.path else "")
        if wanted == self._button_state:
            return
        self._button_state = wanted
        for child in self.buttons.winfo_children():
            child.destroy()
        theme = self.app.theme
        if state.status == "active" and state.direction == "send" and state.batch:
            Button(
                self.buttons,
                theme,
                "Annullér",
                lambda: self.app.cancel_batch(state.batch),
                size="sm",
                kind="ghost",
            ).pack(side="left")
        if state.status == "done" and state.path:
            Button(
                self.buttons,
                theme,
                "Åbn",
                lambda: self.app.open_path_safely(state.path),
                size="sm",
            ).pack(side="left")
            Button(
                self.buttons,
                theme,
                "Vis i mappe",
                lambda: self.app.reveal_path_safely(state.path),
                size="sm",
                kind="ghost",
            ).pack(side="left", padx=(theme.px(6), 0))


class H4xtorShareApp(TkinterDnD.Tk):
    NAV_ITEMS = (
        ("share", "⇄", "Del"),
        ("transfers", "↕", "Overførsler"),
        ("clipboard", "⧉", "Udklipsholder"),
        ("history", "◷", "Historik"),
        ("settings", "⚙", "Indstillinger"),
    )

    def __init__(
        self,
        *,
        start_minimized: bool = False,
        initial_send: list[Path] | None = None,
        enable_tray: bool = True,
    ) -> None:
        super().__init__()
        self.config_store = Config()
        dark = self._wants_dark()
        self.theme = Theme(self, dark)
        self.COLORS = self.theme.c
        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.runtime = AsyncRuntime(self.event_queue)
        certificate, private_key, fingerprint = ensure_certificate(
            self.config_store.path.parent,
            self.config_store.device_name,
        )
        self.fingerprint = fingerprint
        self.client = PeerClient(self.config_store, fingerprint=fingerprint)
        self.server = ShareServer(
            self.config_store,
            server_ssl_context(certificate, private_key),
            fingerprint,
            self._receive_core_event,
        )
        self.discovery = DiscoveryService(
            self.config_store,
            fingerprint,
            self._receive_peer,
            removed_callback=lambda device_id: self.event_queue.put(("peer_gone", device_id)),
        )
        self.udp_discovery = UdpDiscovery(
            self.config_store,
            fingerprint,
            DESKTOP_CAPABILITIES,
            self._receive_peer,
            status_callback=lambda text: self.event_queue.put(("status", text)),
        )
        self.udp_discovery.extra_targets = self._known_addresses
        self.instance = integration.InstanceServer(
            self.config_store.path.parent,
            self.config_store.port + integration.INSTANCE_PORT_OFFSET,
            lambda message: self.event_queue.put(("ipc", message)),
        )
        self.instance.start()
        self.local_api = LocalApi(
            self.config_store,
            self.config_store.port + LOCAL_API_PORT_OFFSET,
            self._api_devices,
            self._api_send,
            self._api_approve,
        )
        self._ipc_paths: list[Path] = []

        self.peers: dict[str, Peer] = {}
        self.peer_status: dict[str, PeerStatus] = {}
        self.peer_misses: dict[str, int] = {}
        self.device_cards: dict[str, DeviceCard] = {}
        self.selected_id: str | None = None
        self.transfers: dict[str, TransferState] = {}
        self.transfer_rows: dict[str, TransferRow] = {}
        self.batches: dict[str, Future[Any]] = {}
        self.history = HistoryStore(self.config_store.history_path)
        self._clipboard_observed = ""
        self._clipboard_suppress_text = ""
        self._clipboard_suppress_until = 0.0
        self._closing = False
        self._qr_modal: Modal | None = None
        self._qr_secret: str | None = None
        self._pair_modals: dict[str, Modal] = {}
        self._previous_wifi: str | None = None
        self.scan_future: Future[Any] | None = None
        self._pending_send: list[Path] = list(initial_send or [])

        self.title(APP_TITLE)
        self.geometry(f"{self.theme.px(1120)}x{self.theme.px(740)}")
        self.minsize(self.theme.px(940), self.theme.px(620))
        self.configure(background=self.theme.c["bg"])
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        self._configure_style()
        self.toast = Toast(self, self.theme)
        self._build_ui()
        set_dark_titlebar(self, dark)

        self.tray: TrayIcon | None = None
        if enable_tray:
            tray = TrayIcon(
                on_open=lambda: self.event_queue.put(("show", None)),
                on_pair=lambda: self.event_queue.put(("show_qr", None)),
                on_quit=lambda: self.event_queue.put(("quit", None)),
            )
            if tray.start():
                self.tray = tray
        if start_minimized and self.tray is not None:
            self.withdraw()

        self.after(100, self._poll_events)
        self.after(600, self._schedule_health_checks)
        self.after(1000, self._schedule_clipboard_watch)
        self.runtime.submit(self._start_services(), "services_started")
        self.runtime.submit(self._check_for_update(), "update_check")
        for peer in self.config_store.known_peers():
            if self.config_store.is_trusted(peer.device_id):
                self._upsert_peer(peer)
        if self._pending_send:
            self.after(800, self._flush_pending_send)
        added = integration.ensure_shell_integration(self.config_store)
        if added:
            self.after(
                1500,
                lambda: self.toast.show(
                    "Klar: højreklik på filer → “Send med h4xtor share”", "success", 6000
                ),
            )

    # ------------------------------------------------------------------ theme
    def _wants_dark(self) -> bool:
        theme = self.config_store.theme
        if theme == "dark":
            return True
        if theme == "light":
            return False
        return integration.system_prefers_dark()

    def _configure_style(self) -> None:
        c = self.theme.c
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=c["card"],
            foreground=c["text"],
            fieldbackground=c["card"],
            rowheight=self.theme.px(34),
            borderwidth=0,
            font=self.theme.font(10),
        )
        style.map(
            "Treeview",
            background=[("selected", c["accent_soft"])],
            foreground=[("selected", c["text"])],
        )
        style.configure(
            "Treeview.Heading",
            background=c["card"],
            foreground=c["muted"],
            relief="flat",
            borderwidth=0,
            font=self.theme.font(9, "bold"),
            padding=(self.theme.px(8), self.theme.px(8)),
        )
        style.map("Treeview.Heading", background=[("active", c["card"])])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Vertical.TScrollbar",
            background=c["border"],
            troughcolor=c["bg"],
            bordercolor=c["bg"],
            arrowcolor=c["muted"],
            relief="flat",
        )
        style.configure(
            "TCombobox",
            fieldbackground=c["entry"],
            background=c["card"],
            foreground=c["text"],
            arrowcolor=c["muted"],
            bordercolor=c["border"],
        )

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        c = self.theme.c
        px = self.theme.px
        self.sidebar = tk.Frame(self, bg=c["sidebar"], width=px(236))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(self, bg=c["border"], width=1).pack(side="left", fill="y")
        self.main = tk.Frame(self, bg=c["bg"])
        self.main.pack(side="left", fill="both", expand=True)
        self._build_sidebar()

        self.status_var = tk.StringVar(value="Starter…")
        self.pages: dict[str, tk.Frame] = {}
        self.page_container = tk.Frame(self.main, bg=c["bg"])
        self.page_container.pack(fill="both", expand=True)
        self.page_container.grid_rowconfigure(0, weight=1)
        self.page_container.grid_columnconfigure(0, weight=1)
        self._build_share_page()
        self._build_transfers_page()
        self._build_clipboard_page()
        self._build_history_page()
        self._build_settings_page()
        for frame in self.pages.values():
            frame.grid(row=0, column=0, sticky="nsew")
        self.show_page("share")

        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<DropEnter>>", lambda _e: self._drop_highlight(True))
        self.dnd_bind("<<DropLeave>>", lambda _e: self._drop_highlight(False))
        self.dnd_bind("<<Drop>>", self._files_dropped)

    def _build_sidebar(self) -> None:
        c = self.theme.c
        px = self.theme.px
        brand = tk.Frame(self.sidebar, bg=c["sidebar"])
        brand.pack(fill="x", padx=px(18), pady=(px(20), px(18)))
        tk.Label(
            brand,
            text="✻",
            bg=c["sidebar"],
            fg=c["accent"],
            font=self.theme.font(17, family=self.theme.symbol),
        ).pack(side="left")
        tk.Label(
            brand,
            text="h4xtor share",
            bg=c["sidebar"],
            fg=c["text"],
            font=self.theme.title_font(15),
        ).pack(side="left", padx=(px(8), 0))

        # "New chat"-style primary action at the top, like Claude.ai.
        new = tk.Frame(self.sidebar, bg=c["sidebar"], cursor="hand2")
        new.pack(fill="x", padx=px(10), pady=(0, px(10)))
        plus = tk.Canvas(new, width=px(26), height=px(26), bg=c["sidebar"], highlightthickness=0)
        plus.create_oval(1, 1, px(26) - 1, px(26) - 1, fill=c["accent"], outline=c["accent"])
        plus.create_text(px(13), px(13), text="+", fill="#FFFFFF", font=self.theme.font(13, "bold"))
        plus.pack(side="left", padx=(px(8), px(10)), pady=px(6))
        new_label = tk.Label(
            new,
            text="Forbind ny enhed",
            bg=c["sidebar"],
            fg=c["accent"],
            font=self.theme.font(10, "bold"),
            anchor="w",
        )
        new_label.pack(side="left", fill="x", expand=True)
        for widget in (new, plus, new_label):
            widget.bind("<Button-1>", lambda _e: self.show_qr_pairing())
            widget.bind(
                "<Enter>",
                lambda _e: [w.configure(bg=c["nav_active"]) for w in (new, plus, new_label)],
            )
            widget.bind(
                "<Leave>", lambda _e: [w.configure(bg=c["sidebar"]) for w in (new, plus, new_label)]
            )

        self.nav_rows: dict[str, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        for key, icon, label in self.NAV_ITEMS:
            row = tk.Frame(self.sidebar, bg=c["sidebar"], cursor="hand2")
            row.pack(fill="x", padx=px(10), pady=px(1))
            icon_label = tk.Label(
                row,
                text=icon,
                width=2,
                bg=c["sidebar"],
                fg=c["muted"],
                font=self.theme.font(12, family=self.theme.symbol),
            )
            icon_label.pack(side="left", padx=(px(9), px(8)), pady=px(7))
            text_label = tk.Label(
                row,
                text=label,
                bg=c["sidebar"],
                fg=c["text"],
                font=self.theme.font(10),
                anchor="w",
            )
            text_label.pack(side="left", fill="x", expand=True)
            badge = tk.Label(
                row, text="", bg=c["sidebar"], fg=c["accent"], font=self.theme.font(9, "bold")
            )
            badge.pack(side="right", padx=px(10))
            for widget in (row, icon_label, text_label, badge):
                widget.bind("<Button-1>", lambda _e, name=key: self.show_page(name))
                widget.bind("<Enter>", lambda _e, name=key: self._nav_hover(name, True))
                widget.bind("<Leave>", lambda _e, name=key: self._nav_hover(name, False))
            self.nav_rows[key] = (row, icon_label, text_label)
            if key == "transfers":
                self.transfer_badge = badge

        spacer = tk.Frame(self.sidebar, bg=c["sidebar"])
        spacer.pack(fill="both", expand=True)

        tk.Frame(self.sidebar, bg=c["border"], height=1).pack(fill="x", padx=px(14))
        me = tk.Frame(self.sidebar, bg=c["sidebar"])
        me.pack(fill="x", padx=px(14), pady=px(14))
        initial = (self.config_store.device_name[:1] or "P").upper()
        badge_canvas = tk.Canvas(
            me, width=px(32), height=px(32), bg=c["sidebar"], highlightthickness=0
        )
        badge_canvas.create_oval(1, 1, px(32) - 1, px(32) - 1, fill=c["text"], outline=c["text"])
        badge_canvas.create_text(
            px(16), px(16), text=initial, fill=c["sidebar"], font=self.theme.font(11, "bold")
        )
        badge_canvas.pack(side="left")
        texts = tk.Frame(me, bg=c["sidebar"])
        texts.pack(side="left", padx=(px(10), 0), fill="x", expand=True)
        self.me_name = tk.Label(
            texts,
            text=self.config_store.device_name,
            bg=c["sidebar"],
            fg=c["text"],
            font=self.theme.font(10, "bold"),
            anchor="w",
        )
        self.me_name.pack(fill="x")
        status_row = tk.Frame(texts, bg=c["sidebar"])
        status_row.pack(fill="x")
        self.me_dot = tk.Label(
            status_row, text="●", bg=c["sidebar"], fg=c["warning"], font=self.theme.font(7)
        )
        self.me_dot.pack(side="left")
        self.me_status = tk.Label(
            status_row,
            text="Starter…",
            bg=c["sidebar"],
            fg=c["muted"],
            font=self.theme.font(8),
            anchor="w",
        )
        self.me_status.pack(side="left", padx=(px(4), 0))
        tk.Label(
            self.sidebar,
            text=f"version {VERSION}",
            bg=c["sidebar"],
            fg=c["faint"],
            font=self.theme.font(7),
        ).pack(anchor="w", padx=px(18), pady=(0, px(10)))

    def _nav_hover(self, name: str, hover: bool) -> None:
        if name == getattr(self, "active_page", ""):
            return
        c = self.theme.c
        color = c["nav_active"] if hover else c["sidebar"]
        for widget in self.nav_rows[name]:
            widget.configure(bg=color)

    def show_page(self, name: str) -> None:
        self.active_page = name
        c = self.theme.c
        for key, (row, icon_label, text_label) in self.nav_rows.items():
            active = key == name
            bg = c["nav_active"] if active else c["sidebar"]
            row.configure(bg=bg)
            icon_label.configure(bg=bg, fg=c["accent"] if active else c["muted"])
            text_label.configure(bg=bg, font=self.theme.font(10, "bold" if active else "normal"))
        for child in self.nav_rows.values():
            for widget in child[0].winfo_children():
                widget.configure(bg=child[0].cget("bg"))
        self.pages[name].tkraise()
        if name == "history":
            self._refresh_history()

    def _page(self, name: str, title: str, subtitle: str) -> tuple[tk.Frame, tk.Frame]:
        c = self.theme.c
        px = self.theme.px
        page = tk.Frame(self.page_container, bg=c["bg"])
        self.pages[name] = page
        header = tk.Frame(page, bg=c["bg"])
        header.pack(fill="x", padx=px(36), pady=(px(30), px(18)))
        texts = tk.Frame(header, bg=c["bg"])
        texts.pack(side="left", fill="x", expand=True)
        tk.Label(
            texts,
            text=title,
            bg=c["bg"],
            fg=c["text"],
            font=self.theme.title_font(20),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            texts,
            text=subtitle,
            bg=c["bg"],
            fg=c["muted"],
            font=self.theme.font(10),
            anchor="w",
        ).pack(fill="x", pady=(px(3), 0))
        actions = tk.Frame(header, bg=c["bg"])
        actions.pack(side="right", anchor="s")
        return page, actions

    # ------------------------------------------------------------- share page
    def _build_share_page(self) -> None:
        c = self.theme.c
        px = self.theme.px
        page = tk.Frame(self.page_container, bg=c["bg"])
        self.pages["share"] = page

        top = tk.Frame(page, bg=c["bg"])
        top.pack(fill="x", padx=px(24), pady=(px(14), 0))
        Button(
            top, self.theme, "Tilføj via IP", self.add_manual_peer, kind="ghost", size="sm"
        ).pack(side="right")
        Button(
            top, self.theme, "Scan netværk", self.scan_lan, kind="ghost", size="sm", icon="⟳"
        ).pack(side="right", padx=(0, px(4)))

        scroll = ScrollFrame(page, self.theme)
        scroll.pack(fill="both", expand=True)
        outer = scroll.inner
        center = tk.Frame(outer, bg=c["bg"])
        center.pack(fill="x", padx=px(48), pady=(px(26), px(30)))

        def recenter(event: tk.Event) -> None:
            pad = max(px(32), (event.width - px(760)) // 2)
            center.pack_configure(padx=pad)

        scroll.canvas.bind("<Configure>", recenter, add="+")

        self.banner = tk.Frame(center, bg=c["bg"])
        self.banner.pack(fill="x")

        hero = tk.Frame(center, bg=c["bg"])
        hero.pack(pady=(px(18), px(22)))
        Monkey(hero, self.theme, size=px(72)).pack(side="left", padx=(0, px(16)))
        self.greeting_label = tk.Label(
            hero,
            text="Velkommen til H4xtor Share",
            bg=c["bg"],
            fg=c["text"],
            font=self.theme.title_font(26),
        )
        self.greeting_label.pack(side="left")

        # The composer: Claude's prompt box, but for files, links and text.
        self.composer = Card(center, self.theme, padding=14, radius=20, outline=c["border_strong"])
        self.composer.pack(fill="x")
        body = self.composer.body
        self._composer_placeholder = (
            "Skriv en besked eller indsæt et link …  eller træk filer hertil"
        )
        self.composer_text = tk.Text(
            body,
            height=3,
            bg=c["card"],
            fg=c["faint"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
            font=self.theme.font(11),
            wrap="word",
            padx=px(4),
            pady=px(4),
        )
        self.composer_text.insert("1.0", self._composer_placeholder)
        self.composer_text.pack(fill="x")
        self.composer_text.bind("<FocusIn>", lambda _e: self._composer_focus(True))
        self.composer_text.bind("<FocusOut>", lambda _e: self._composer_focus(False))
        self.composer_text.bind("<Return>", self._composer_enter)

        bar = tk.Frame(body, bg=c["card"])
        bar.pack(fill="x", pady=(px(8), 0))
        Button(
            bar,
            self.theme,
            "Filer",
            lambda: self.send_files(),
            kind="ghost",
            size="sm",
            icon="＋",
            bg=c["card"],
        ).pack(side="left")
        Button(
            bar,
            self.theme,
            "Mappe",
            lambda: self.send_folder(),
            kind="ghost",
            size="sm",
            icon="▤",
            bg=c["card"],
        ).pack(side="left")
        Button(
            bar,
            self.theme,
            "Udklipsholder",
            lambda: self.send_clipboard(),
            kind="ghost",
            size="sm",
            icon="⧉",
            bg=c["card"],
        ).pack(side="left")
        self.send_button = Button(
            bar,
            self.theme,
            "",
            self._composer_send,
            kind="primary",
            icon="↑",
            size="md",
            width=36,
            bg=c["card"],
        )
        self.send_button.pack(side="right")
        self.target_button = Button(
            bar,
            self.theme,
            "Vælg modtager ▾",
            self._choose_target,
            kind="ghost",
            size="sm",
            bg=c["card"],
        )
        self.target_button.pack(side="right", padx=(0, px(6)))

        self.composer_hint = tk.Label(
            center,
            text="",
            bg=c["bg"],
            fg=c["faint"],
            font=self.theme.font(9),
        )
        self.composer_hint.pack(pady=(px(8), 0))
        self._drop_active = False

        # Sections
        section = tk.Frame(center, bg=c["bg"])
        section.pack(fill="x", pady=(px(30), 0))
        self.paired_title = tk.Label(
            section,
            text="Dine enheder",
            bg=c["bg"],
            fg=c["muted"],
            font=self.theme.font(9, "bold"),
            anchor="w",
        )
        self.paired_title.pack(fill="x", pady=(0, px(8)))
        self.paired_empty = self._build_empty_state(section)
        self.paired_list = tk.Frame(section, bg=c["bg"])
        self.paired_list.pack(fill="x")

        self.lan_section = tk.Frame(center, bg=c["bg"])
        head = tk.Frame(self.lan_section, bg=c["bg"])
        head.pack(fill="x", pady=(0, px(2)))
        self.lan_title = tk.Label(
            head,
            text="Fundet på netværket",
            bg=c["bg"],
            fg=c["muted"],
            font=self.theme.font(9, "bold"),
            anchor="w",
        )
        self.lan_title.pack(side="left")
        tk.Label(
            self.lan_section,
            text=(
                "Enheder med h4xtor share på dit Wi-Fi, som du ikke har forbundet. "
                "Klik Forbind – eller ✕ for at skjule."
            ),
            bg=c["bg"],
            fg=c["faint"],
            font=self.theme.font(8),
            anchor="w",
        ).pack(fill="x", pady=(0, px(8)))
        self.lan_list = tk.Frame(self.lan_section, bg=c["bg"])
        self.lan_list.pack(fill="x")
        self.device_list = self.paired_list
        self._reorder_cards()
        self._draw_drop_zone()

    def _build_empty_state(self, parent: tk.Misc) -> tk.Frame:
        c = self.theme.c
        px = self.theme.px
        frame = tk.Frame(parent, bg=c["bg"])
        tk.Label(
            frame,
            text="Ingen forbundne enheder endnu. Kom i gang med et af disse:",
            bg=c["bg"],
            fg=c["muted"],
            font=self.theme.font(10),
            anchor="w",
        ).pack(fill="x", pady=(0, px(10)))
        chips = tk.Frame(frame, bg=c["bg"])
        chips.pack(fill="x")
        for label, icon, command in (
            ("Forbind din telefon med QR", "▣", self.show_qr_pairing),
            ("Scan netværket", "⟳", self.scan_lan),
            ("Tilføj via IP-adresse", "⌁", self.add_manual_peer),
        ):
            Button(chips, self.theme, label, command, kind="secondary", size="sm", icon=icon).pack(
                side="left", padx=(0, px(8))
            )
        return frame

    def _composer_focus(self, focused: bool) -> None:
        c = self.theme.c
        text = self.composer_text.get("1.0", "end").strip()
        if focused and text == self._composer_placeholder:
            self.composer_text.delete("1.0", "end")
            self.composer_text.configure(fg=c["text"])
        elif not focused and not text:
            self.composer_text.insert("1.0", self._composer_placeholder)
            self.composer_text.configure(fg=c["faint"])

    def _composer_value(self) -> str:
        text = self.composer_text.get("1.0", "end").strip()
        return "" if text == self._composer_placeholder else text

    def _composer_enter(self, event: tk.Event) -> str | None:
        if event.state & 0x1:  # Shift+Enter: new line
            return None
        self._composer_send()
        return "break"

    def _composer_send(self) -> None:
        text = self._composer_value()
        if not text:
            self.send_files()
            return

        def deliver(peer: Peer) -> None:
            self._send_text(peer, text)
            self.composer_text.delete("1.0", "end")
            self.toast.show(
                f"Link sendt til {peer.name} – åbner i browseren"
                if is_link(text)
                else f"Tekst sendt til {peer.name} – klar i udklipsholderen",
                "success",
            )

        target = self._drop_target_peer()
        if target is not None:
            deliver(target)
        else:
            self._choose_peer(deliver, "Send til…")

    def _choose_target(self) -> None:
        trusted = [p for p in self.peers.values() if self.config_store.is_trusted(p.device_id)]
        if not trusted:
            self.show_qr_pairing()
            return
        menu = tk.Menu(self, tearoff=0)
        for peer in sorted(trusted, key=lambda item: item.name.lower()):
            status = self.peer_status.get(peer.device_id)
            online = status is not None and status.online
            mark = "✓ " if self.selected_id == peer.device_id else "   "
            menu.add_command(
                label=f"{mark}{peer.name}   ({'online' if online else 'offline'})",
                command=lambda value=peer.device_id: self.select_peer(value),
            )
        menu.add_separator()
        menu.add_command(label="Forbind ny enhed…", command=self.show_qr_pairing)
        x = self.target_button.winfo_rootx()
        y = self.target_button.winfo_rooty() + self.target_button.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _draw_drop_zone(self) -> None:
        """Refresh the composer: target chip, drop highlight and hint line."""
        if not hasattr(self, "composer"):
            return
        c = self.theme.c
        target = self._drop_target_peer()
        self.target_button.set_text(f"Til: {target.name} ▾" if target else "Vælg modtager ▾")
        active = self._drop_active
        self.composer.set_colors(outline=c["accent"] if active else c["border_strong"])
        if active:
            hint = (
                f"Slip for at sende til {target.name}" if target else "Slip – så vælger du modtager"
            )
            self.composer_hint.configure(text=hint, fg=c["accent"])
        elif target is not None:
            self.composer_hint.configure(
                text="Enter sender · Shift+Enter ny linje · links åbner direkte i browseren",
                fg=c["faint"],
            )
        else:
            self.composer_hint.configure(
                text="Forbind en enhed for at begynde at dele", fg=c["faint"]
            )

    def _drop_highlight(self, active: bool) -> str:
        self._drop_active = active
        self._draw_drop_zone()
        return "copy"

    def _drop_target_peer(self) -> Peer | None:
        if self.selected_id and self.config_store.is_trusted(self.selected_id):
            return self.peers.get(self.selected_id)
        trusted = [
            peer for peer in self.peers.values() if self.config_store.is_trusted(peer.device_id)
        ]
        online = [
            peer
            for peer in trusted
            if (status := self.peer_status.get(peer.device_id)) is not None and status.online
        ]
        if len(online) == 1:
            return online[0]
        if len(trusted) == 1:
            return trusted[0]
        return None

    def select_peer(self, device_id: str) -> None:
        self.selected_id = device_id
        for card in self.device_cards.values():
            card.update(card.peer)
        self._draw_drop_zone()

    # ---------------------------------------------------------- transfers page
    def _build_transfers_page(self) -> None:
        px = self.theme.px
        page, actions = self._page(
            "transfers", "Overførsler", "Alt der sendes og modtages – live, og kan genoptages."
        )
        Button(actions, self.theme, "Ryd færdige", self.clear_finished_transfers).pack(side="left")
        Button(
            actions, self.theme, "Åbn modtaget-mappe", self.open_incoming_folder, kind="ghost"
        ).pack(side="left", padx=(px(8), 0))
        self.transfer_scroll = ScrollFrame(page, self.theme)
        self.transfer_scroll.pack(fill="both", expand=True, padx=(px(36), px(24)), pady=(0, px(16)))
        self.transfer_empty = tk.Label(
            self.transfer_scroll.inner,
            text="Ingen overførsler endnu. Træk en fil ind på Del-siden for at komme i gang.",
            bg=self.theme.c["bg"],
            fg=self.theme.c["muted"],
            font=self.theme.font(10),
            anchor="w",
        )
        self.transfer_empty.pack(fill="x", pady=px(8))

    # ---------------------------------------------------------- clipboard page
    def _build_clipboard_page(self) -> None:
        c = self.theme.c
        px = self.theme.px
        page, _actions = self._page(
            "clipboard", "Udklipsholder", "Kopiér på én enhed – sæt ind på en anden."
        )
        scroll = ScrollFrame(page, self.theme)
        scroll.pack(fill="both", expand=True, padx=(px(36), px(24)), pady=(0, px(16)))
        inner = scroll.inner

        settings = Card(inner, self.theme)
        settings.pack(fill="x", pady=(0, px(14)))
        self._toggle_row(
            settings.body,
            "Synkronisér automatisk",
            "Ny tekst du kopierer sendes til alle forbundne enheder.",
            self.config_store.clipboard_sync_enabled,
            lambda value: setattr(self.config_store, "clipboard_sync_enabled", value),
        )
        self._divider(settings.body)
        self._toggle_row(
            settings.body,
            "Indsæt modtaget tekst i udklipsholderen",
            "Tekst fra dine andre enheder er klar til Ctrl+V med det samme.",
            self.config_store.apply_received_clipboard,
            lambda value: setattr(self.config_store, "apply_received_clipboard", value),
        )
        self._divider(settings.body)
        self._toggle_row(
            settings.body,
            "Åbn modtagne links automatisk",
            "Links du sender fra telefonen åbner direkte i din browser.",
            self.config_store.open_links,
            lambda value: setattr(self.config_store, "open_links", value),
        )

        compose = Card(inner, self.theme)
        compose.pack(fill="x", pady=(0, px(14)))
        tk.Label(
            compose.body,
            text="Send tekst eller link",
            bg=c["card"],
            fg=c["text"],
            font=self.theme.font(11, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            compose.body,
            text=(
                "Et link åbnes i browseren på modtageren. "
                "Almindelig tekst lander i udklipsholderen."
            ),
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
        ).pack(fill="x", pady=(px(2), px(10)))
        self.compose_box = tk.Text(
            compose.body,
            height=4,
            bg=c["entry"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["border"],
            highlightcolor=c["accent"],
            font=self.theme.font(10),
            wrap="word",
            padx=px(10),
            pady=px(8),
        )
        self.compose_box.pack(fill="x")
        row = tk.Frame(compose.body, bg=c["card"])
        row.pack(fill="x", pady=(px(10), 0))
        Button(
            row, self.theme, "Send til alle forbundne", self._send_compose_to_all, kind="primary"
        ).pack(side="left")
        Button(row, self.theme, "Vælg enhed…", self._send_compose_pick).pack(
            side="left", padx=(px(8), 0)
        )

        tk.Label(
            inner,
            text="SENESTE",
            bg=c["bg"],
            fg=c["faint"],
            font=self.theme.font(8, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(px(4), px(8)))
        self.recent_clips = tk.Frame(inner, bg=c["bg"])
        self.recent_clips.pack(fill="x")
        self._refresh_recent_clips()

    def _toggle_row(
        self,
        parent: tk.Misc,
        title: str,
        subtitle: str,
        value: bool,
        command: Any,
    ) -> Toggle:
        c = self.theme.c
        px = self.theme.px
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.pack(fill="x", pady=px(2))
        texts = tk.Frame(row, bg=parent.cget("bg"))
        texts.pack(side="left", fill="x", expand=True)
        tk.Label(
            texts,
            text=title,
            bg=parent.cget("bg"),
            fg=c["text"],
            font=self.theme.font(10, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            texts,
            text=subtitle,
            bg=parent.cget("bg"),
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
            justify="left",
            wraplength=px(520),
        ).pack(fill="x")
        toggle = Toggle(row, self.theme, value, command)
        toggle.pack(side="right", padx=(px(12), 0))
        return toggle

    def _divider(self, parent: tk.Misc) -> None:
        tk.Frame(parent, bg=self.theme.c["border"], height=1).pack(fill="x", pady=self.theme.px(12))

    def _refresh_recent_clips(self) -> None:
        if not hasattr(self, "recent_clips"):
            return
        c = self.theme.c
        px = self.theme.px
        for child in self.recent_clips.winfo_children():
            child.destroy()
        items: list[tuple[str, dict[str, Any]]] = []
        for direction, entries in (("↓", self.history.received()), ("↑", self.history.sent())):
            for item in entries:
                if item.get("kind") in {"clipboard", "link"}:
                    items.append((direction, item))
        items.sort(key=lambda pair: str(pair[1].get("ts", "")), reverse=True)
        if not items:
            tk.Label(
                self.recent_clips,
                text="Intet endnu.",
                bg=c["bg"],
                fg=c["muted"],
                font=self.theme.font(10),
                anchor="w",
            ).pack(fill="x")
            return
        for direction, item in items[:8]:
            card = Card(self.recent_clips, self.theme, padding=12, radius=10)
            card.pack(fill="x", pady=(0, px(8)))
            text = str(item.get("text", ""))
            preview = text.replace("\n", " ")
            if len(preview) > 110:
                preview = preview[:110] + "…"
            tk.Label(
                card.body,
                text=f"{direction}  {preview}",
                bg=c["card"],
                fg=c["text"],
                font=self.theme.font(10),
                anchor="w",
            ).pack(side="left", fill="x", expand=True)
            tk.Label(
                card.body,
                text=str(item.get("peer", "")),
                bg=c["card"],
                fg=c["faint"],
                font=self.theme.font(9),
            ).pack(side="left", padx=px(10))
            Button(
                card.body,
                self.theme,
                "Kopiér",
                lambda value=text: self._copy_to_clipboard(value),
                size="sm",
            ).pack(side="right")
            if item.get("kind") == "link":
                Button(
                    card.body,
                    self.theme,
                    "Åbn",
                    lambda value=text: self._open_link(value),
                    size="sm",
                    kind="ghost",
                ).pack(side="right", padx=(0, px(6)))

    def _copy_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self._clipboard_observed = text
        self.toast.show("Kopieret til udklipsholderen", "success")

    # ------------------------------------------------------------ history page
    def _build_history_page(self) -> None:
        c = self.theme.c
        px = self.theme.px
        page, actions = self._page("history", "Historik", "Alt du har sendt og modtaget.")
        Button(actions, self.theme, "Åbn", self.open_received_file).pack(side="left")
        Button(actions, self.theme, "Vis i mappe", self.reveal_received_file, kind="ghost").pack(
            side="left", padx=(px(8), 0)
        )

        segments = tk.Frame(page, bg=c["bg"])
        segments.pack(fill="x", padx=px(36), pady=(0, px(12)))
        self.history_mode = "received"
        self.history_segments: dict[str, Button] = {}
        for key, label in (("received", "Modtaget"), ("sent", "Sendt"), ("devices", "Enheder")):
            button = Button(
                segments,
                self.theme,
                label,
                lambda name=key: self._set_history_mode(name),
                size="sm",
                kind="ghost",
            )
            button.pack(side="left", padx=(0, px(6)))
            self.history_segments[key] = button

        card = Card(page, self.theme, padding=8)
        card.pack(fill="both", expand=True, padx=px(36), pady=(0, px(24)))
        card.body.configure(height=px(400))
        card.body.pack_propagate(False)
        self.history_tree = ttk.Treeview(card.body, show="headings", selectmode="browse")
        scrollbar = ttk.Scrollbar(card.body, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.history_tree.pack(fill="both", expand=True)
        self.history_tree.bind("<Double-1>", lambda _e: self.open_received_file())
        card.bind(
            "<Configure>",
            lambda e: card.body.configure(height=max(px(120), e.height - 2 * card.padding)),
            add="+",
        )
        self._set_history_mode("received")

    def _set_history_mode(self, mode: str) -> None:
        self.history_mode = mode
        for key, button in self.history_segments.items():
            button.kind = "soft" if key == mode else "ghost"
            button._draw()
        self._refresh_history()

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_tree"):
            return
        tree = self.history_tree
        tree.delete(*tree.get_children())
        if self.history_mode == "devices":
            columns = (
                ("name", "Enhed", 200),
                ("ip", "IP", 140),
                ("os", "System", 100),
                ("last_seen", "Sidst set", 170),
                ("connections", "Forbindelser", 110),
            )
        else:
            columns = (
                ("kind", "Type", 90),
                ("name", "Hvad", 340),
                ("peer", "Enhed", 160),
                ("size", "Størrelse", 100),
                ("ts", "Tidspunkt", 190),
            )
        tree.configure(columns=tuple(name for name, _title, _width in columns))
        for name, title, width in columns:
            tree.heading(name, text=title, anchor="w")
            tree.column(name, width=self.theme.px(width), anchor="w", stretch=name == "name")
        kinds = {"file": "Fil", "folder": "Mappe", "clipboard": "Tekst", "link": "Link"}
        if self.history_mode == "devices":
            for index, item in enumerate(self.history.devices()):
                tree.insert(
                    "",
                    "end",
                    iid=f"d{index}",
                    values=(
                        item.get("name", ""),
                        item.get("ip", ""),
                        PLATFORM_LABELS.get(str(item.get("os", "")).lower(), item.get("os", "")),
                        str(item.get("last_seen", "")).replace("T", "  "),
                        item.get("connections", 0),
                    ),
                )
            return
        entries = (
            self.history.received() if self.history_mode == "received" else self.history.sent()
        )
        for index in range(len(entries) - 1, -1, -1):
            item = entries[index]
            size = int(item.get("size") or 0)
            tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    kinds.get(str(item.get("kind")), item.get("kind", "")),
                    str(item.get("text", "")).replace("\n", " ")[:200],
                    item.get("peer", ""),
                    _format_bytes(size) if size else "",
                    str(item.get("ts", "")).replace("T", "  "),
                ),
            )

    # ----------------------------------------------------------- settings page
    def _build_settings_page(self) -> None:
        c = self.theme.c
        px = self.theme.px
        page, _actions = self._page("settings", "Indstillinger", "Gør h4xtor share til din egen.")
        scroll = ScrollFrame(page, self.theme)
        scroll.pack(fill="both", expand=True, padx=(px(36), px(24)), pady=(0, px(16)))
        inner = scroll.inner

        def section(title: str) -> Card:
            tk.Label(
                inner,
                text=title.upper(),
                bg=c["bg"],
                fg=c["faint"],
                font=self.theme.font(8, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(px(6), px(8)))
            card = Card(inner, self.theme)
            card.pack(fill="x", pady=(0, px(16)))
            return card

        device = section("Denne enhed")
        tk.Label(
            device.body,
            text="Navn som andre enheder ser",
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
        ).pack(fill="x")
        name_row = tk.Frame(device.body, bg=c["card"])
        name_row.pack(fill="x", pady=(px(6), 0))
        self.device_name_var = tk.StringVar(value=self.config_store.device_name)
        entry(name_row, self.theme, self.device_name_var).pack(
            side="left", fill="x", expand=True, ipady=px(6)
        )
        Button(name_row, self.theme, "Gem", self.save_device_name).pack(
            side="left", padx=(px(8), 0)
        )
        tk.Label(
            device.body,
            text=f"Enheds-id {self.config_store.device_id[:12]}…  ·  "
            f"certifikat {self.fingerprint[:16]}…",
            bg=c["card"],
            fg=c["faint"],
            font=self.theme.font(8, family=self.theme.mono),
            anchor="w",
        ).pack(fill="x", pady=(px(10), 0))

        files = section("Modtagne filer")
        tk.Label(
            files.body,
            text="Gemmes i",
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
        ).pack(fill="x")
        folder_row = tk.Frame(files.body, bg=c["card"])
        folder_row.pack(fill="x", pady=(px(6), 0))
        self.incoming_var = tk.StringVar(value=str(self.config_store.incoming_directory))
        entry(
            folder_row,
            self.theme,
            self.incoming_var,
            state="readonly",
            readonlybackground=c["entry"],
        ).pack(side="left", fill="x", expand=True, ipady=px(6))
        Button(folder_row, self.theme, "Skift…", self.choose_incoming_folder).pack(
            side="left", padx=(px(8), 0)
        )
        Button(folder_row, self.theme, "Åbn", self.open_incoming_folder, kind="ghost").pack(
            side="left", padx=(px(6), 0)
        )

        behaviour = section("Opførsel")
        self._toggle_row(
            behaviour.body,
            "Start sammen med computeren",
            "Kører diskret i baggrunden, så telefonen altid kan sende til dig.",
            self._safe_autostart_state(),
            self._set_autostart,
        )
        if platform.system() == "Windows":
            self._divider(behaviour.body)
            self._toggle_row(
                behaviour.body,
                "Højreklik i Stifinder",
                "“Send med h4xtor share” på filer og mapper (Windows 11: Vis flere indstillinger) "
                "samt Send til → h4xtor-share.",
                integration.is_context_menu_installed() or integration.is_send_to_installed(),
                self._set_shell_menu,
            )
        self._divider(behaviour.body)
        self._toggle_row(
            behaviour.body,
            "Luk til proceslinjen",
            "Når du lukker vinduet, kører h4xtor share videre ved uret.",
            self.config_store.get_flag("close_to_tray", True),
            lambda value: self.config_store.set_flag("close_to_tray", value),
        )
        self._divider(behaviour.body)
        theme_row = tk.Frame(behaviour.body, bg=c["card"])
        theme_row.pack(fill="x")
        tk.Label(
            theme_row,
            text="Tema",
            bg=c["card"],
            fg=c["text"],
            font=self.theme.font(10, "bold"),
        ).pack(side="left")
        self.theme_buttons: dict[str, Button] = {}
        for key, label in (("dark", "Mørkt"), ("light", "Lyst"), ("system", "Automatisk")):
            button = Button(
                theme_row,
                self.theme,
                label,
                lambda value=key: self._set_theme(value),
                size="sm",
                kind="soft" if self.config_store.theme == key else "ghost",
            )
            button.pack(side="right", padx=(px(6), 0))
            self.theme_buttons[key] = button

        browser = section("Links og Chrome")
        browser_row = tk.Frame(browser.body, bg=c["card"])
        browser_row.pack(fill="x")
        texts = tk.Frame(browser_row, bg=c["card"])
        texts.pack(side="left", fill="x", expand=True)
        tk.Label(
            texts,
            text="Åbn modtagne links i",
            bg=c["card"],
            fg=c["text"],
            font=self.theme.font(10, "bold"),
            anchor="w",
        ).pack(fill="x")
        chrome_found = integration.find_chrome() is not None
        tk.Label(
            texts,
            text="Google Chrome er fundet på denne PC."
            if chrome_found
            else "Chrome blev ikke fundet – standardbrowseren bruges.",
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
        ).pack(fill="x")
        current = str(self.config_store.data.get("link_browser") or "chrome")
        self.browser_buttons: dict[str, Button] = {}
        for key, label in (("default", "Standardbrowser"), ("chrome", "Chrome")):
            button = Button(
                browser_row,
                self.theme,
                label,
                lambda value=key: self._set_link_browser(value),
                size="sm",
                kind="soft" if current == key else "ghost",
            )
            button.pack(side="right", padx=(px(6), 0))
            self.browser_buttons[key] = button
        self._divider(browser.body)
        ext_row = tk.Frame(browser.body, bg=c["card"])
        ext_row.pack(fill="x")
        ext_texts = tk.Frame(ext_row, bg=c["card"])
        ext_texts.pack(side="left", fill="x", expand=True)
        tk.Label(
            ext_texts,
            text="Chrome-udvidelse",
            bg=c["card"],
            fg=c["text"],
            font=self.theme.font(10, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            ext_texts,
            text=(
                "Højreklik på en side, et link, et billede eller markeret tekst "
                "→ send til telefonen."
            ),
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
        ).pack(fill="x")
        Button(ext_row, self.theme, "Installér", self.install_chrome_extension, size="sm").pack(
            side="right"
        )

        direct = section("Wi-Fi Direct")
        tk.Label(
            direct.body,
            text=(
                "Del uden router: Tryk “Wi-Fi Direct” i h4xtor share på telefonen. Er telefonen "
                "allerede forbundet, kobler PC'en selv på. Ellers indtast netværk og kode herunder."
            ),
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
            justify="left",
            wraplength=px(620),
        ).pack(fill="x")
        wifi_row = tk.Frame(direct.body, bg=c["card"])
        wifi_row.pack(fill="x", pady=(px(10), 0))
        self.wifi_ssid_var = tk.StringVar(value="")
        self.wifi_pass_var = tk.StringVar(value="")
        entry(wifi_row, self.theme, self.wifi_ssid_var, width=24).pack(side="left", ipady=px(6))
        entry(wifi_row, self.theme, self.wifi_pass_var, width=20, show="•").pack(
            side="left", padx=(px(8), 0), ipady=px(6)
        )
        Button(
            wifi_row,
            self.theme,
            "Forbind",
            lambda: self.join_wifi_direct(self.wifi_ssid_var.get(), self.wifi_pass_var.get()),
            kind="primary",
        ).pack(side="left", padx=(px(8), 0))
        tk.Label(
            direct.body,
            text="Netværksnavn (DIRECT-…)        Adgangskode",
            bg=c["card"],
            fg=c["faint"],
            font=self.theme.font(8),
            anchor="w",
        ).pack(fill="x", pady=(px(4), 0))

        self.paired_section = section("Forbundne enheder")
        self._refresh_paired_list()

        about = section("Om")
        tk.Label(
            about.body,
            text=(
                f"h4xtor share {VERSION}  ·  Helt lokalt – ingen konto, ingen sky.\n"
                "Alt krypteres med TLS og låses til enhedens certifikat ved parring."
            ),
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
            justify="left",
        ).pack(fill="x")

    def _refresh_paired_list(self) -> None:
        if not hasattr(self, "paired_section"):
            return
        c = self.theme.c
        px = self.theme.px
        body = self.paired_section.body
        for child in body.winfo_children():
            child.destroy()
        ids = self.config_store.trusted_peer_ids()
        if not ids:
            tk.Label(
                body,
                text="Ingen endnu. Brug “Forbind ny enhed” i menuen til venstre.",
                bg=c["card"],
                fg=c["muted"],
                font=self.theme.font(10),
                anchor="w",
            ).pack(fill="x")
            return
        for index, peer_id in enumerate(ids):
            if index:
                tk.Frame(body, bg=c["border"], height=1).pack(fill="x", pady=px(8))
            peer = self.peers.get(peer_id)
            name = (
                peer.name
                if peer
                else self.config_store.data["trusted_peers"][peer_id].get("name", peer_id)
            )
            row = tk.Frame(body, bg=c["card"])
            row.pack(fill="x")
            Avatar(row, self.theme, peer.platform if peer else "", size=30).pack(side="left")
            tk.Label(
                row,
                text=name,
                bg=c["card"],
                fg=c["text"],
                font=self.theme.font(10, "bold"),
            ).pack(side="left", padx=(px(10), 0))
            target = peer or Peer(peer_id, name, "0.0.0.0", self.config_store.port, "", "unknown")
            Button(
                row,
                self.theme,
                "Glem",
                lambda value=target: self.forget_peer(value),
                size="sm",
                kind="danger",
            ).pack(side="right")

    def _safe_autostart_state(self) -> bool:
        try:
            return integration.is_autostart_enabled()
        except Exception:  # noqa: BLE001
            return False

    def _set_autostart(self, value: bool) -> None:
        try:
            integration.set_autostart(value)
        except Exception as error:  # noqa: BLE001
            self._show_error(error)
            return
        self.toast.show("Starter nu sammen med computeren" if value else "Autostart slået fra")

    def _set_shell_menu(self, value: bool) -> None:
        try:
            if value:
                integration.install_context_menu()
                integration.install_send_to()
            else:
                integration.remove_context_menu()
                integration.remove_send_to()
        except Exception as error:  # noqa: BLE001
            self._show_error(error)
            return
        self.toast.show("Højreklik-menuen er klar" if value else "Højreklik-menuen er fjernet")

    def _set_link_browser(self, value: str) -> None:
        self.config_store.data["link_browser"] = value
        self.config_store.save()
        for key, button in self.browser_buttons.items():
            button.kind = "soft" if key == value else "ghost"
            button._draw()

    def _set_send_to(self, value: bool) -> None:
        try:
            if value:
                integration.install_send_to()
            else:
                integration.remove_send_to()
        except Exception as error:  # noqa: BLE001
            self._show_error(error)
            return
        self.toast.show("“Send til” er klar i Stifinder" if value else "“Send til” fjernet")

    def _set_theme(self, value: str) -> None:
        self.config_store.theme = value
        for key, button in self.theme_buttons.items():
            button.kind = "soft" if key == value else "ghost"
            button._draw()
        self.toast.show("Temaet skifter næste gang h4xtor share starter.")

    # ---------------------------------------------------------------- services
    async def _start_services(self) -> None:
        await self.server.start()
        try:
            await asyncio.to_thread(self.discovery.start)
        except Exception as error:  # noqa: BLE001 - UDP and scanning still work
            self.event_queue.put(("status", f"mDNS utilgængelig: {error}"))
        await asyncio.to_thread(self.udp_discovery.start)
        try:
            await self.local_api.start()
        except OSError as error:
            self.event_queue.put(
                ("status", f"Chrome-udvidelsens forbindelse er utilgængelig: {error}")
            )

    async def _check_for_update(self) -> tuple[str, str] | None:
        """Ask GitHub (best effort, internet optional) whether a newer release exists."""
        import aiohttp

        url = "https://api.github.com/repos/h4xtor/h4xtor-share/releases/latest"
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with (
                aiohttp.ClientSession(timeout=timeout, trust_env=True) as session,
                session.get(url, headers={"Accept": "application/vnd.github+json"}) as response,
            ):
                if response.status != 200:
                    return None
                payload = await response.json()
        except Exception:  # noqa: BLE001 - offline is perfectly fine
            return None
        tag = str(payload.get("tag_name") or "")
        if is_newer_version(tag, VERSION):
            return tag.lstrip("v"), str(payload.get("html_url") or "")
        return None

    async def _stop_services(self) -> None:
        with contextlib.suppress(Exception):
            await self.local_api.stop()
        await asyncio.to_thread(self.udp_discovery.stop)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self.discovery.stop)
        await self.server.stop()

    def _known_addresses(self) -> list[str]:
        return [peer.address for peer in self.config_store.known_peers()]

    def _receive_core_event(self, event: object) -> None:
        self.event_queue.put(("core_event", event))

    def _receive_peer(self, peer: Peer) -> None:
        self.event_queue.put(("peer", peer))

    def _poll_events(self) -> None:
        if self._closing:
            return
        deadline = time.monotonic() + 0.05
        try:
            while time.monotonic() < deadline:
                tag, value = self.event_queue.get_nowait()
                try:
                    self._handle_event(tag, value)
                except Exception as error:  # noqa: BLE001 - never kill the UI loop
                    self.status_var.set(str(error))
        except queue.Empty:
            pass
        self.after(60, self._poll_events)

    def _handle_event(self, tag: str, value: Any) -> None:
        if tag == "error":
            self._show_error(value)
        elif tag == "cancelled":
            pass
        elif tag == "update_check":
            if value:
                self._show_update_banner(*value)
        elif tag == "services_started":
            self._set_me_status()
        elif tag == "peer_gone":
            if not self.config_store.is_trusted(value):
                self._remove_peer_card(value)
        elif tag in {"peer", "manual_peer", "scan_peer"}:
            if tag != "peer":
                self.config_store.unhide_peer(value.device_id)
            self._upsert_peer(value)
            if tag == "manual_peer":
                self.select_peer(value.device_id)
                self.toast.show(f"Fandt {value.name}", "success")
        elif tag == "core_event":
            self._handle_core_event(value)
        elif tag == "scan_progress":
            done, total = value
            self.status_var.set(f"Scanner netværket: {done}/{total}")
        elif tag == "scan_complete":
            self.scan_future = None
            self.toast.show(f"Netværksscanning færdig – {len(value)} enhed(er) fundet")
        elif tag == "pair_requested":
            peer, response = value
            self._prompt_for_pairing_code(peer, response)
        elif tag == "pair_confirmed":
            peer = value
            if isinstance(peer, Peer):
                self.config_store.unhide_peer(peer.device_id)
                self._upsert_peer(peer)
                self.select_peer(peer.device_id)
                self.toast.show(f"Forbundet med {peer.name}", "success")
            self._refresh_paired_list()
            self._refresh_device_cards()
        elif tag == "clipboard_sent":
            self.toast.show("Sendt ✓", "success")
            self._refresh_recent_clips()
        elif tag == "batch_done":
            batch, peer_name, count = value
            self.batches.pop(batch, None)
            self._refresh_history()
            self.toast.show(f"{_items(count)} sendt til {peer_name}", "success")
            self._update_transfer_badge()
        elif tag == "batch_failed":
            batch, error = value
            self.batches.pop(batch, None)
            self._mark_batch(batch, "failed")
            self._show_error(error)
        elif tag == "batch_cancelled":
            self.batches.pop(value, None)
            self._mark_batch(value, "cancelled")
        elif tag == "peer_status":
            self._update_peer_status(value)
        elif tag == "status":
            self.status_var.set(value)
        elif tag == "clipboard_broadcast":
            self._refresh_recent_clips()
        elif tag == "wifi_joined":
            peer = value
            self._upsert_peer(peer)
            self.select_peer(peer.device_id)
            self._show_wifi_banner()
            self.toast.show(f"Forbundet direkte med {peer.name} via Wi-Fi Direct", "success")
        elif tag == "wifi_restored":
            self._show_wifi_banner()
            self.toast.show("Tilbage på dit normale Wi-Fi")
        elif tag == "unpaired":
            self._remove_peer_card(value)
            self._refresh_paired_list()
        elif tag == "approve_extension":
            self._ask_extension_approval(value)
        elif tag == "ipc":
            self._handle_ipc(value)
        elif tag == "show":
            self.show_window()
        elif tag == "show_qr":
            self.show_window()
            self.show_qr_pairing()
        elif tag == "quit":
            self.quit_app()

    def _set_me_status(self) -> None:
        addresses = _sorted_lan_addresses()
        self.me_dot.configure(fg=self.theme.c["success"])
        shown = addresses[0] if addresses else "ingen netværk"
        self.me_status.configure(text=f"Online  ·  {shown}")
        self.status_var.set("Online")

    def _show_error(self, error: BaseException) -> None:
        message = friendly_error(error, self.peers.values())
        self.status_var.set(message)
        self.toast.show(message, "danger", duration_ms=6000)

    def _notify(self, message: str, tone: str = "neutral") -> None:
        self.toast.show(message, tone)
        if self.tray is not None and not self.winfo_viewable():
            self.tray.notify(message)

    def _handle_core_event(self, event: object) -> None:
        if isinstance(event, tuple):
            self._update_transfer(event)
            return
        if isinstance(event, PairingPrompt):
            self._show_pairing_code(event)
        elif isinstance(event, PeerPaired):
            self.config_store.unhide_peer(event.peer.device_id)
            self._upsert_peer(event.peer)
            modal = self._pair_modals.pop(event.peer.device_id, None)
            if modal is not None:
                modal.close()
            if self._qr_modal is not None:
                self._qr_modal.close()
            self.select_peer(event.peer.device_id)
            self._refresh_paired_list()
            self.show_window()
            self._notify(f"Forbundet med {event.peer.name}", "success")
        elif isinstance(event, PeerForgotten):
            self._remove_peer_card(event.peer_id)
            self._refresh_paired_list()
            self._notify(f"{event.peer_name} har afbrudt forbindelsen")
        elif isinstance(event, ClipboardReceived):
            if self.config_store.apply_received_clipboard:
                self.clipboard_clear()
                self.clipboard_append(event.text)
                self.update_idletasks()
                self._clipboard_observed = event.text
                self._clipboard_suppress_text = event.text
                self._clipboard_suppress_until = time.monotonic() + CLIPBOARD_SUPPRESS_SECONDS
            self._record_remote_text(event.peer_id, event.text, received=True)
            if is_link(event.text) and self.config_store.open_links:
                self._open_link(event.text.strip())
                self._notify(f"Link fra {event.peer_name} åbnet")
            else:
                self._notify(f"Udklipsholder fra {event.peer_name} – klar til Ctrl+V")
        elif isinstance(event, LinkReceived):
            self._record_remote_text(event.peer_id, event.url, received=True)
            if self.config_store.open_links:
                used = self._open_link(event.url)
                where = "Chrome" if used == "chrome" else "browseren"
                self._notify(f"Link fra {event.peer_name} åbnet i {where}")
            else:
                self._copy_to_clipboard(event.url)
                self._notify(f"Link fra {event.peer_name} kopieret")
        elif isinstance(event, FileReceived | FolderReceived):
            is_folder = isinstance(event, FolderReceived)
            peer = self.peers.get(event.peer_id)
            if peer is not None:
                record = (
                    self.history.record_received_folder
                    if is_folder
                    else self.history.record_received_file
                )
                record(peer, event.path.name, event.size, str(event.path))
            state = self.transfers.get(event.transfer_id) if event.transfer_id else None
            if state is None:
                state = TransferState(
                    transfer_id=event.transfer_id or str(event.path),
                    name=event.path.name,
                    direction="receive",
                    peer_name=event.peer_name,
                    total=event.size,
                )
                self.transfers[state.transfer_id] = state
            state.status = "done"
            state.sent = state.total = event.size
            state.path = str(event.path)
            self._render_transfer(state)
            self._refresh_history()
            kind = "Mappe" if is_folder else "Fil"
            self._notify(f"{kind} modtaget fra {event.peer_name}: {event.path.name}", "success")
        elif isinstance(event, TransferProgress):
            self._update_transfer(event)
        elif isinstance(event, WifiDirectOffer):
            self._offer_wifi_direct(event)

    def _record_remote_text(self, peer_id: str, text: str, received: bool) -> None:
        peer = self.peers.get(peer_id)
        if peer is None:
            return
        if received:
            self.history.record_received_text(peer, text)
        else:
            self.history.record_sent_text(peer, text)
        self._refresh_recent_clips()

    # ---------------------------------------------------------------- devices
    def _upsert_peer(self, peer: Peer) -> None:
        trusted = self.config_store.is_trusted(peer.device_id)
        if not trusted and peer.device_id in self.config_store.hidden_peers():
            return
        # One address = one device. A different id on the same address is either a
        # stale record (old mDNS cache, reinstalled app) or a reused DHCP lease.
        for other_id, other in list(self.peers.items()):
            if other_id == peer.device_id or other.address != peer.address:
                continue
            if other.port != peer.port:
                continue
            other_trusted = self.config_store.is_trusted(other_id)
            other_status = self.peer_status.get(other_id)
            if not other_trusted:
                self._remove_peer_card(other_id)
            elif not trusted and other_status is not None and other_status.online:
                return  # the paired device is alive on this address; this one is stale
        existing = self.peers.get(peer.device_id)
        if existing is not None and existing.address != peer.address:
            status = self.peer_status.get(peer.device_id)
            if status is not None and status.online and existing.transport == "wifi-direct":
                # Keep a working direct link instead of flapping to the LAN address.
                peer = Peer(
                    peer.device_id,
                    peer.name,
                    existing.address,
                    existing.port,
                    peer.fingerprint or existing.fingerprint,
                    peer.platform,
                    existing.transport,
                    peer.capabilities or existing.capabilities,
                )
            elif status is not None and status.online:
                self.event_queue.put(("status", f"{peer.name} fundet på {peer.address}"))
        if existing is not None and not peer.capabilities:
            peer = Peer(
                peer.device_id,
                peer.name,
                peer.address,
                peer.port,
                peer.fingerprint or existing.fingerprint,
                peer.platform,
                peer.transport,
                existing.capabilities,
            )
        self.peers[peer.device_id] = peer
        if self.config_store.is_trusted(peer.device_id):
            self.config_store.remember_peer(peer)
        card = self.device_cards.get(peer.device_id)
        if card is None:
            card = DeviceCard(self, self.device_list, peer)
            self.device_cards[peer.device_id] = card
        else:
            card.update(peer)
        self._reorder_cards()
        self._draw_drop_zone()

    def _reorder_cards(self) -> None:
        """Lay out the two sections: paired devices, then devices only found on the LAN."""
        px = self.theme.px

        def sort_key(peer: Peer) -> tuple[int, str]:
            status = self.peer_status.get(peer.device_id)
            return (0 if status is not None and status.online else 1, peer.name.lower())

        for card in self.device_cards.values():
            if card.card is not None:
                card.card.pack_forget()
        paired = [c.peer for c in self.device_cards.values() if c._mode == "paired"]
        lan = [c.peer for c in self.device_cards.values() if c._mode == "lan"]
        for peer in sorted(paired, key=sort_key):
            card = self.device_cards[peer.device_id].card
            assert card is not None
            card.pack(fill="x", pady=(0, px(8)))
        for peer in sorted(lan, key=sort_key):
            card = self.device_cards[peer.device_id].card
            assert card is not None
            card.pack(fill="x", pady=(0, px(8)))
        online = sum(
            1
            for peer in paired
            if (status := self.peer_status.get(peer.device_id)) is not None and status.online
        )
        self.paired_title.configure(
            text=f"Dine enheder  ·  {online} online" if paired else "Dine enheder"
        )
        if paired:
            self.paired_empty.pack_forget()
        else:
            self.paired_empty.pack(fill="x", before=self.paired_list)
        if lan:
            self.lan_section.pack(fill="x", pady=(px(18), 0))
            self.lan_title.configure(text=f"Fundet på netværket  ·  {len(lan)}")
        else:
            self.lan_section.pack_forget()

    def _refresh_device_cards(self) -> None:
        for card in self.device_cards.values():
            card.update(card.peer)
        self._reorder_cards()
        self._draw_drop_zone()

    def remove_device(self, peer: Peer) -> None:
        """Remove a device from the list; paired devices are also unpaired."""
        if self.config_store.is_trusted(peer.device_id):
            self.forget_peer(peer)
        else:
            self.config_store.hide_peer(peer.device_id)
            self._remove_peer_card(peer.device_id)
            self.toast.show(f"{peer.name} er fjernet fra listen")

    def confirm_remove(self, peer: Peer) -> None:
        c = self.theme.c
        px = self.theme.px
        paired = self.config_store.is_trusted(peer.device_id)
        modal = Modal(self, self.theme, "Fjern enhed")
        modal.heading(
            f"Fjern {peer.name}?",
            "I skal forbinde igen for at dele. Den anden enhed glemmer også denne PC."
            if paired
            else "Enheden skjules. Den dukker op igen, hvis du scanner netværket eller parrer.",
        )
        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(20), 0))

        def remove() -> None:
            modal.close()
            self.remove_device(peer)

        Button(buttons, self.theme, "Fjern", remove, kind="danger").pack(side="right")
        Button(buttons, self.theme, "Annullér", modal.close, kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        modal.present()

    def _remove_peer_card(self, peer_id: str) -> None:
        self.peer_misses.pop(peer_id, None)
        card = self.device_cards.pop(peer_id, None)
        if card is not None:
            card.destroy()
        self.peers.pop(peer_id, None)
        self.peer_status.pop(peer_id, None)
        if self.selected_id == peer_id:
            self.selected_id = None
        self._reorder_cards()
        self._draw_drop_zone()

    def _update_peer_status(self, status: PeerStatus) -> None:
        peer = self.peers.get(status.device_id)
        if peer is None:
            return
        if status.online:
            self.peer_misses.pop(status.device_id, None)
        elif not self.config_store.is_trusted(status.device_id):
            misses = self.peer_misses.get(status.device_id, 0) + 1
            self.peer_misses[status.device_id] = misses
            if misses >= 3:
                # Unpaired devices that stopped answering simply disappear.
                self._remove_peer_card(status.device_id)
                return
        previous = self.peer_status.get(status.device_id)
        self.peer_status[status.device_id] = status
        if previous is None or previous.online != status.online:
            self.history.record_connection(peer, status.online, status.rtt_ms)
            card = self.device_cards.get(peer.device_id)
            if card is not None:
                card.update(peer)
            self._reorder_cards()
            self._draw_drop_zone()
        else:
            card = self.device_cards.get(peer.device_id)
            if card is not None:
                card.update(peer)

    async def _check_peer_health(self) -> None:
        peers = list(self.peers.values())
        if not peers:
            return
        results = await asyncio.gather(
            *(self.client.ping(peer) for peer in peers),
            return_exceptions=True,
        )
        for peer, result in zip(peers, results, strict=True):
            if isinstance(result, BaseException):
                self.event_queue.put(("peer_status", PeerStatus(peer.device_id, False, None)))
            else:
                self.event_queue.put(("peer_status", PeerStatus(peer.device_id, True, result)))

    def _schedule_health_checks(self) -> None:
        if self._closing:
            return
        self.runtime.submit(self._check_peer_health(), "health_cycle")
        self.after(HEALTH_INTERVAL_MS, self._schedule_health_checks)

    def selected_peer(self) -> Peer:
        peer = self._drop_target_peer()
        if peer is None:
            raise RuntimeError("Vælg en forbundet enhed først.")
        return peer

    def add_manual_peer(self) -> None:
        modal = Modal(self, self.theme, "Tilføj via IP")
        modal.heading(
            "Tilføj enhed via IP-adresse",
            "Brug det her, hvis enheden ikke dukker op af sig selv – fx på gæste-Wi-Fi.",
        )
        c = self.theme.c
        px = self.theme.px
        address = tk.StringVar()
        port = tk.StringVar(value=str(self.config_store.port))
        row = tk.Frame(modal.body, bg=c["bg"])
        row.pack(fill="x", pady=(px(16), 0))
        address_entry = entry(row, self.theme, address, width=22)
        address_entry.pack(side="left", ipady=px(7))
        entry(row, self.theme, port, width=7).pack(side="left", padx=(px(8), 0), ipady=px(7))

        def submit() -> None:
            try:
                port_value = int(port.get())
            except ValueError:
                self._show_error(ValueError("Porten skal være et tal."))
                return
            value = address.get().strip()
            if not value:
                return
            modal.close()
            self.runtime.submit(self.client.get_info(value, port_value), "manual_peer")

        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(20), 0))
        Button(buttons, self.theme, "Tilføj", submit, kind="primary").pack(side="right")
        Button(buttons, self.theme, "Annullér", modal.close, kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        modal.bind("<Return>", lambda _e: submit())
        modal.present()
        address_entry.focus_set()

    def scan_lan(self) -> None:
        if self.scan_future is not None and not self.scan_future.done():
            self.toast.show("Scanner allerede…")
            return
        self.toast.show("Scanner dit netværk efter enheder…")
        self.scan_future = self.runtime.submit(
            scan_lan_peers(
                self.client,
                self.config_store.port,
                peer_callback=lambda peer: self.event_queue.put(("scan_peer", peer)),
                progress_callback=lambda done, total: self.event_queue.put(
                    ("scan_progress", (done, total))
                ),
            ),
            "scan_complete",
        )

    def forget_peer(self, peer: Peer) -> None:
        async def run() -> str:
            await self.client.unpair(peer)
            return peer.device_id

        self.runtime.submit(run(), "unpaired")
        self.toast.show(f"{peer.name} er glemt")

    # ---------------------------------------------------------------- pairing
    def pair_with_code(self, peer: Peer) -> None:
        self.toast.show(f"Beder {peer.name} om en kode…")

        async def request() -> tuple[Peer, dict[str, Any]]:
            return peer, await self.client.request_pairing(peer)

        self.runtime.submit(request(), "pair_requested")

    def pair_selected(self) -> None:
        peer = self.peers.get(self.selected_id or "")
        if peer is not None:
            self.pair_with_code(peer)

    def _prompt_for_pairing_code(self, peer: Peer, response: dict[str, Any]) -> None:
        c = self.theme.c
        px = self.theme.px
        modal = Modal(self, self.theme, "Forbind")
        modal.heading(
            f"Forbind med {peer.name}",
            "Skriv den 6-cifrede kode, der lige er dukket op på den anden enhed.",
        )
        code = tk.StringVar()
        field_ = tk.Entry(
            modal.body,
            textvariable=code,
            justify="center",
            bg=c["entry"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=2,
            highlightbackground=c["border"],
            highlightcolor=c["accent"],
            font=self.theme.font(26, "bold", self.theme.mono),
            width=8,
        )
        field_.pack(pady=(px(20), px(6)), ipady=px(8))

        def submit() -> None:
            value = code.get().replace(" ", "").strip()
            if len(value) != 6 or not value.isdigit():
                self._show_error(ValueError("Koden består af 6 cifre."))
                return
            modal.close()

            async def confirm() -> Peer:
                await self.client.confirm_pairing(peer, str(response["pairing_id"]), value)
                return peer

            self.runtime.submit(confirm(), "pair_confirmed")

        code.trace_add(
            "write", lambda *_a: submit() if len(code.get().replace(" ", "")) == 6 else None
        )
        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(16), 0))
        Button(buttons, self.theme, "Forbind", submit, kind="primary").pack(side="right")
        Button(buttons, self.theme, "Annullér", modal.close, kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        modal.bind("<Return>", lambda _e: submit())
        modal.present()
        field_.focus_set()

    def _show_pairing_code(self, event: PairingPrompt) -> None:
        c = self.theme.c
        px = self.theme.px
        self.show_window()
        modal = Modal(self, self.theme, "Forbindelsesanmodning")
        modal.heading(
            f"{event.peer_name} vil forbinde",
            "Indtast koden på den anden enhed. Afvis, hvis du ikke selv har bedt om det.",
        )
        digits = f"{event.code[:3]} {event.code[3:]}"
        tk.Label(
            modal.body,
            text=digits,
            bg=c["bg"],
            fg=c["accent"],
            font=self.theme.font(34, "bold", self.theme.mono),
        ).pack(pady=(px(18), px(4)))
        countdown = tk.Label(
            modal.body, text="", bg=c["bg"], fg=c["muted"], font=self.theme.font(9)
        )
        countdown.pack()

        def tick() -> None:
            remaining = int(event.expires_at - time.time())
            if remaining <= 0:
                modal.close()
                return
            with contextlib.suppress(tk.TclError):
                countdown.configure(text=f"Koden udløber om {remaining} s")
                modal.after(1000, tick)

        tick()

        def reject() -> None:
            self.server.pending_pairings.pop(event.pairing_id, None)
            modal.close()

        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(18), 0))
        Button(buttons, self.theme, "OK", modal.close, kind="primary").pack(side="right")
        Button(buttons, self.theme, "Afvis", reject, kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        self._pair_modals[event.peer_id] = modal
        modal.present()
        if self.tray is not None:
            self.tray.notify(f"{event.peer_name} vil forbinde – kode {digits}")

    def _current_invite(self) -> PairingInvite:
        self._qr_secret = self.server.create_qr_secret()
        return PairingInvite(
            device_id=self.config_store.device_id,
            name=self.config_store.device_name,
            fingerprint=self.fingerprint,
            port=self.config_store.port,
            addresses=tuple(_sorted_lan_addresses()[:3]) or ("127.0.0.1",),
            secret=self._qr_secret,
            platform=self.config_store.platform_name,
        )

    def show_qr_pairing(self) -> None:
        if self._qr_modal is not None:
            with contextlib.suppress(tk.TclError):
                self._qr_modal.lift()
                return
        c = self.theme.c
        px = self.theme.px
        modal = Modal(self, self.theme, "Forbind ny enhed", width=640)
        self._qr_modal = modal
        layout = tk.Frame(modal.body, bg=c["bg"])
        layout.pack(fill="both", expand=True)
        qr_card = Card(layout, self.theme, padding=12, fill="#FFFFFF", outline=c["border"])
        qr_card.configure(width=px(236) + 2 * px(12))
        qr_card.pack(side="left", anchor="n")
        qr = QrCanvas(qr_card.body, self.theme, size=236)
        qr.pack()

        info = tk.Frame(layout, bg=c["bg"])
        info.pack(side="left", fill="both", expand=True, padx=(px(26), 0))
        tk.Label(
            info,
            text="Forbind en enhed",
            bg=c["bg"],
            fg=c["text"],
            font=self.theme.title_font(16),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            info,
            text="Det tager 5 sekunder – og kun første gang.",
            bg=c["bg"],
            fg=c["muted"],
            font=self.theme.font(10),
            anchor="w",
        ).pack(fill="x", pady=(px(2), px(16)))
        for number, text in (
            ("1", "Åbn h4xtor share på telefonen"),
            ("2", "Tryk på “Scan QR-kode”"),
            ("3", "Peg kameraet mod koden – færdig!"),
        ):
            row = tk.Frame(info, bg=c["bg"])
            row.pack(fill="x", pady=px(5))
            tk.Label(
                row,
                text=number,
                width=2,
                bg=c["accent_soft"],
                fg=c["accent"],
                font=self.theme.font(10, "bold"),
            ).pack(side="left")
            tk.Label(
                row, text=text, bg=c["bg"], fg=c["text"], font=self.theme.font(10), anchor="w"
            ).pack(side="left", padx=(px(10), 0))
        tk.Label(
            info,
            text="Koden er engangs og udløber efter få minutter. Forbindelsen krypteres og låses "
            "til denne PC's certifikat.",
            bg=c["bg"],
            fg=c["faint"],
            font=self.theme.font(8),
            anchor="w",
            justify="left",
            wraplength=px(300),
        ).pack(fill="x", pady=(px(14), 0))

        other = tk.Frame(modal.body, bg=c["bg"])
        other.pack(fill="x", pady=(px(22), 0))
        tk.Frame(other, bg=c["border"], height=1).pack(fill="x", pady=(0, px(14)))
        tk.Label(
            other,
            text="Har du et parringslink fra en anden computer?",
            bg=c["bg"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
        ).pack(fill="x")
        link_row = tk.Frame(other, bg=c["bg"])
        link_row.pack(fill="x", pady=(px(6), 0))
        link_var = tk.StringVar()
        entry(link_row, self.theme, link_var).pack(side="left", fill="x", expand=True, ipady=px(6))
        Button(
            link_row,
            self.theme,
            "Forbind",
            lambda: self.pair_from_link(link_var.get(), modal),
        ).pack(side="left", padx=(px(8), 0))
        Button(
            link_row,
            self.theme,
            "Kopiér mit link",
            lambda: self._copy_to_clipboard(invite_holder["uri"]),
            kind="ghost",
        ).pack(side="left", padx=(px(6), 0))

        invite_holder: dict[str, str] = {}

        def refresh() -> None:
            if self._qr_modal is not modal:
                return
            if self._qr_secret:
                self.server.revoke_qr_secret(self._qr_secret)
            invite = self._current_invite()
            invite_holder["uri"] = invite.to_uri()
            qr.show(qr_matrix(invite_holder["uri"]))
            modal.after(QR_REFRESH_MS, refresh)

        def closed() -> None:
            if self._qr_secret:
                self.server.revoke_qr_secret(self._qr_secret)
                self._qr_secret = None
            self._qr_modal = None

        modal.on_close = closed
        refresh()
        modal.present()

    def pair_from_link(self, text: str, modal: Modal | None = None) -> None:
        try:
            invite = parse_invite(text)
        except ValueError as error:
            self._show_error(error)
            return
        if modal is not None:
            modal.close()
        self.toast.show(f"Forbinder til {invite.name}…")
        self.runtime.submit(self.client.pair_with_qr(invite), "pair_confirmed")

    # ----------------------------------------------------------- Wi-Fi Direct
    def _offer_wifi_direct(self, offer: WifiDirectOffer) -> None:
        c = self.theme.c
        px = self.theme.px
        self.show_window()
        modal = Modal(self, self.theme, "Wi-Fi Direct")
        modal.heading(
            f"{offer.peer_name} tilbyder en direkte forbindelse",
            f"PC'en skifter til telefonens Wi-Fi Direct-netværk ({offer.ssid}). Det er "
            "lynhurtigt og virker uden router – men mens du er forbundet, har PC'en "
            "normalt ikke internet via Wi-Fi. Du kan skifte tilbage med ét klik.",
        )
        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(20), 0))

        def accept() -> None:
            modal.close()
            self.join_wifi_direct(offer.ssid, offer.passphrase, offer.owner_address, offer.port)

        Button(buttons, self.theme, "Forbind direkte", accept, kind="primary").pack(side="right")
        Button(buttons, self.theme, "Ikke nu", modal.close, kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        modal.present()

    def join_wifi_direct(
        self,
        ssid: str,
        passphrase: str,
        owner: str = wifidirect.ANDROID_GROUP_OWNER,
        port: int | None = None,
    ) -> None:
        ssid = ssid.strip()
        if not ssid or len(passphrase) < 8:
            self._show_error(ValueError("Skriv netværksnavn og en kode på mindst 8 tegn."))
            return
        target_port = port or self.config_store.port
        self.toast.show(f"Forbinder til {ssid}…", duration_ms=8000)

        async def run() -> Peer:
            previous = await asyncio.to_thread(wifidirect.current_wifi_ssid)
            if previous and previous != ssid:
                self._previous_wifi = previous
            await asyncio.to_thread(wifidirect.connect_to_group, ssid, passphrase)
            last: Exception | None = None
            for _attempt in range(10):
                try:
                    peer = await self.client.get_info(owner, target_port, timeout_seconds=3)
                except Exception as error:  # noqa: BLE001
                    last = error
                    await asyncio.sleep(1)
                    continue
                return Peer(
                    peer.device_id,
                    peer.name,
                    peer.address,
                    peer.port,
                    peer.fingerprint,
                    peer.platform,
                    "wifi-direct",
                    peer.capabilities,
                )
            raise RuntimeError(f"Telefonen svarer ikke på Wi-Fi Direct: {last}")

        self.runtime.submit(run(), "wifi_joined")

    def restore_wifi(self) -> None:
        previous = self._previous_wifi
        if not previous:
            return

        async def run() -> None:
            await asyncio.to_thread(wifidirect.reconnect, previous)

        self._previous_wifi = None
        self.runtime.submit(run(), "wifi_restored")

    def _show_update_banner(self, version: str, url: str) -> None:
        c = self.theme.c
        px = self.theme.px
        card = Card(
            self.banner, self.theme, padding=12, fill=c["accent_soft"], outline=c["accent_soft"]
        )
        card.pack(fill="x", pady=(0, px(6)))
        tk.Label(
            card.body,
            text=f"Ny version {version} er klar  ·  du kører {VERSION}",
            bg=c["accent_soft"],
            fg=c["accent"],
            font=self.theme.font(10, "bold"),
        ).pack(side="left")
        Button(
            card.body,
            self.theme,
            "Hent opdatering",
            lambda: webbrowser.open(url),
            kind="primary",
            size="sm",
        ).pack(side="right")

    def _show_wifi_banner(self) -> None:
        if not hasattr(self, "wifi_banner"):
            self.wifi_banner = tk.Frame(self.banner, bg=self.theme.c["bg"])
            self.wifi_banner.pack(fill="x")
        for child in self.wifi_banner.winfo_children():
            child.destroy()
        if not self._previous_wifi or not wifidirect.p2p_address():
            return
        c = self.theme.c
        px = self.theme.px
        card = Card(
            self.wifi_banner,
            self.theme,
            padding=12,
            fill=c["accent_soft"],
            outline=c["accent_soft"],
        )
        card.pack(fill="x", pady=(0, px(14)))
        tk.Label(
            card.body,
            text="⚡  Forbundet via Wi-Fi Direct",
            bg=c["accent_soft"],
            fg=c["accent"],
            font=self.theme.font(10, "bold"),
        ).pack(side="left")
        Button(
            card.body,
            self.theme,
            f"Tilbage til {self._previous_wifi}",
            self.restore_wifi,
            size="sm",
        ).pack(side="right")

    # ---------------------------------------------------------------- sending
    def _resolve_peer(self, peer: Peer | None, retry: Any) -> Peer | None:
        """Explicit peer, else the obvious target, else ask the user to pick one."""
        if peer is not None:
            return peer
        target = self._drop_target_peer()
        if target is None:
            self._choose_peer(retry, "Vælg en enhed")
        return target

    def send_clipboard(self, peer: Peer | None = None) -> None:
        target = self._resolve_peer(peer, self.send_clipboard)
        if target is None:
            return
        try:
            text = self.clipboard_get()
        except tk.TclError:
            self._show_error(RuntimeError("Udklipsholderen er tom."))
            return
        self._send_text(target, text)

    def _send_text(self, peer: Peer, text: str) -> None:
        text = text.strip("\n")
        if not text:
            return
        self._clipboard_observed = text
        self.history.record_sent_text(peer, text)
        if is_link(text):
            coroutine = self.client.send_link(peer, text.strip())
        else:
            coroutine = self.client.send_clipboard(peer, text)
        self.runtime.submit(coroutine, "clipboard_sent")

    def compose_text(self, peer: Peer) -> None:
        c = self.theme.c
        px = self.theme.px
        modal = Modal(self, self.theme, "Send tekst eller link", width=520)
        modal.heading(
            f"Send til {peer.name}",
            "Links åbner i browseren på modtageren. Tekst havner i udklipsholderen.",
        )
        box = tk.Text(
            modal.body,
            height=6,
            bg=c["entry"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["border"],
            highlightcolor=c["accent"],
            font=self.theme.font(10),
            wrap="word",
            padx=px(10),
            pady=px(8),
        )
        box.pack(fill="x", pady=(px(16), 0))
        with contextlib.suppress(tk.TclError):
            clip = self.clipboard_get()
            if clip and len(clip) < 4000:
                box.insert("1.0", clip)
                box.tag_add("sel", "1.0", "end")

        def submit() -> None:
            text = box.get("1.0", "end").strip()
            modal.close()
            self._send_text(peer, text)

        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(16), 0))
        Button(buttons, self.theme, "Send", submit, kind="primary").pack(side="right")
        Button(buttons, self.theme, "Annullér", modal.close, kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        modal.bind("<Control-Return>", lambda _e: submit())
        modal.present()
        box.focus_set()

    def _send_compose_to_all(self) -> None:
        text = self.compose_box.get("1.0", "end").strip()
        if not text:
            return
        targets = [
            peer for peer in self.peers.values() if self.config_store.is_trusted(peer.device_id)
        ]
        if not targets:
            self._show_error(RuntimeError("Ingen forbundne enheder endnu."))
            return
        for peer in targets:
            self._send_text(peer, text)
        self.compose_box.delete("1.0", "end")

    def _send_compose_pick(self) -> None:
        text = self.compose_box.get("1.0", "end").strip()
        if not text:
            return

        def chosen(peer: Peer) -> None:
            self._send_text(peer, text)
            self.compose_box.delete("1.0", "end")

        self._choose_peer(chosen, "Send tekst til…")

    def _choose_peer(self, callback: Any, title: str, subtitle: str = "") -> None:
        trusted = [
            peer for peer in self.peers.values() if self.config_store.is_trusted(peer.device_id)
        ]
        if not trusted:
            self.show_qr_pairing()
            return
        if len(trusted) == 1:
            callback(trusted[0])
            return
        c = self.theme.c
        px = self.theme.px
        modal = Modal(self, self.theme, title)
        modal.heading(title, subtitle)
        for peer in sorted(trusted, key=lambda item: item.name.lower()):
            status = self.peer_status.get(peer.device_id)
            online = status is not None and status.online
            card = Card(modal.body, self.theme, padding=12, radius=10)
            card.pack(fill="x", pady=(px(10), 0))
            Avatar(card.body, self.theme, peer.platform, size=32).pack(side="left")
            tk.Label(
                card.body,
                text=peer.name,
                bg=c["card"],
                fg=c["text"],
                font=self.theme.font(10, "bold"),
            ).pack(side="left", padx=(px(10), 0))
            tk.Label(
                card.body,
                text="online" if online else "offline",
                bg=c["card"],
                fg=c["success"] if online else c["faint"],
                font=self.theme.font(9),
            ).pack(side="left", padx=(px(8), 0))

            def pick(value: Peer = peer) -> None:
                modal.close()
                callback(value)

            Button(card.body, self.theme, "Vælg", pick, kind="primary", size="sm").pack(
                side="right"
            )
        modal.present()

    def send_files(self, peer: Peer | None = None) -> None:
        target = self._resolve_peer(peer, self.send_files)
        if target is None:
            return
        paths = filedialog.askopenfilenames(title=f"Send filer til {target.name}", parent=self)
        if paths:
            self._send_paths(target, [Path(raw) for raw in paths])

    def send_folder(self, peer: Peer | None = None) -> None:
        target = self._resolve_peer(peer, self.send_folder)
        if target is None:
            return
        if not target.supports_folders:
            self._show_error(RuntimeError(f"{target.name} kan ikke modtage mapper endnu."))
            return
        path = filedialog.askdirectory(
            title=f"Send mappe til {target.name}", initialdir=str(Path.home()), parent=self
        )
        if path:
            self._send_paths(target, [Path(path)])

    def _files_dropped(self, event: Any) -> str:
        self._drop_highlight(False)
        paths = [Path(raw) for raw in self.tk.splitlist(event.data)]
        paths = [path for path in paths if path.exists()]
        if not paths:
            self._show_error(ValueError("Der var ingen filer i det, du slap."))
            return "break"
        target = self._drop_target_peer()
        if target is not None:
            self._send_paths(target, paths)
        else:
            self._choose_peer(
                lambda peer: self._send_paths(peer, paths),
                "Hvor skal filerne hen?",
                f"{_items(len(paths))} klar til at blive sendt.",
            )
        return "break"

    def _send_paths(self, peer: Peer, paths: list[Path]) -> None:
        files = [path for path in paths if path.is_file()]
        folders = [path for path in paths if path.is_dir()]
        if folders and not peer.supports_folders:
            self._show_error(RuntimeError(f"{peer.name} kan ikke modtage mapper endnu."))
            folders = []
        if not files and not folders:
            return
        batch = f"b{time.monotonic_ns()}"

        def progress_callback(transfer_progress: TransferProgress) -> None:
            self.event_queue.put(("core_event", (batch, peer.name, transfer_progress)))

        def folder_size(path: Path) -> int:
            return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())

        async def send_all() -> None:
            semaphore = asyncio.Semaphore(SEND_CONCURRENCY)

            async def send_one(path: Path) -> None:
                async with semaphore:
                    if path.is_dir():
                        await self.client.send_folder(peer, path, progress_callback)
                        self.history.record_sent_folder(
                            peer, path.name, folder_size(path), str(path)
                        )
                    else:
                        size = path.stat().st_size
                        await self.client.send_file(peer, path, progress_callback)
                        self.history.record_sent_file(peer, path.name, size, str(path))

            try:
                await asyncio.gather(*(send_one(path) for path in files + folders))
            except asyncio.CancelledError:
                self.event_queue.put(("batch_cancelled", batch))
                raise
            except Exception as error:
                self.event_queue.put(("batch_failed", (batch, error)))
                raise
            self.event_queue.put(("batch_done", (batch, peer.name, len(files) + len(folders))))

        count = len(files) + len(folders)
        self.toast.show(f"Sender {_items(count)} til {peer.name}…")
        future = asyncio.run_coroutine_threadsafe(send_all(), self.runtime.loop)
        self.batches[batch] = future
        self.show_page("transfers")

    def cancel_batch(self, batch: str) -> None:
        future = self.batches.get(batch)
        if future is not None:
            future.cancel()
        self._mark_batch(batch, "cancelled")

    def _mark_batch(self, batch: str, status: str) -> None:
        for state in self.transfers.values():
            if state.batch == batch and state.status == "active":
                state.status = status
                self._render_transfer(state)
        self._update_transfer_badge()

    # -------------------------------------------------------------- transfers
    def _update_transfer(self, progress: Any) -> None:
        batch = ""
        peer_name = ""
        if isinstance(progress, tuple):
            batch, peer_name, progress = progress
        assert isinstance(progress, TransferProgress)
        state = self.transfers.get(progress.transfer_id)
        now = time.monotonic()
        if state is None:
            state = TransferState(
                transfer_id=progress.transfer_id,
                name=progress.file_name,
                direction=progress.direction,
                peer_name=peer_name or progress.peer_name or "anden enhed",
                total=progress.total,
                sent=progress.sent,
                last_sent=progress.sent,
                batch=batch,
            )
            self.transfers[progress.transfer_id] = state
        else:
            elapsed = now - state.last_time
            if elapsed >= 0.25:
                instantaneous = (progress.sent - state.last_sent) / elapsed
                state.speed = (
                    instantaneous if state.speed <= 0 else state.speed * 0.7 + instantaneous * 0.3
                )
                state.last_time = now
                state.last_sent = progress.sent
            state.sent = progress.sent
            state.total = progress.total
            if state.status in {"cancelled", "failed"}:
                state.status = "active"
            if batch:
                state.batch = batch
        if progress.direction == "send" and progress.total and progress.sent >= progress.total:
            state.status = "done"
        self._render_transfer(state)

    def _render_transfer(self, state: TransferState) -> None:
        row = self.transfer_rows.get(state.transfer_id)
        if row is None:
            self.transfer_empty.pack_forget()
            row = TransferRow(self, self.transfer_scroll.inner, state)
            existing = [r.card for r in self.transfer_rows.values()]
            if existing:
                row.card.pack(fill="x", pady=(0, self.theme.px(10)), before=existing[-1])
            else:
                row.card.pack(fill="x", pady=(0, self.theme.px(10)))
            self.transfer_rows[state.transfer_id] = row
            self._trim_transfers()
        else:
            row.state = state
            row.refresh()
        self._update_transfer_badge()

    def _trim_transfers(self) -> None:
        while len(self.transfer_rows) > MAX_TRANSFER_ROWS:
            oldest = next(
                (key for key, row in self.transfer_rows.items() if row.state.status != "active"),
                None,
            )
            if oldest is None:
                break
            self.transfer_rows.pop(oldest).card.destroy()
            self.transfers.pop(oldest, None)

    def _update_transfer_badge(self) -> None:
        active = sum(1 for state in self.transfers.values() if state.status == "active")
        self.transfer_badge.configure(text=str(active) if active else "")

    @property
    def transfer_bars(self) -> dict[str, ProgressBar]:
        return {key: row.bar for key, row in self.transfer_rows.items()}

    def clear_finished_transfers(self) -> None:
        for key in [k for k, row in self.transfer_rows.items() if row.state.status != "active"]:
            self.transfer_rows.pop(key).card.destroy()
            self.transfers.pop(key, None)
        if not self.transfer_rows:
            self.transfer_empty.pack(fill="x", pady=self.theme.px(8))

    # -------------------------------------------------------------- clipboard
    def _schedule_clipboard_watch(self) -> None:
        if self._closing:
            return
        try:
            self._poll_clipboard()
        finally:
            self.after(CLIPBOARD_POLL_MS, self._schedule_clipboard_watch)

    def _poll_clipboard(self) -> None:
        if not self.config_store.clipboard_sync_enabled:
            return
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        if not text or text == self._clipboard_observed:
            return
        if (
            text == self._clipboard_suppress_text
            and time.monotonic() < self._clipboard_suppress_until
        ):
            self._clipboard_observed = text
            return
        first = not self._clipboard_observed
        self._clipboard_observed = text
        if first:
            return  # do not broadcast whatever was on the clipboard at startup
        targets = [
            peer
            for peer in self.peers.values()
            if self.config_store.is_trusted(peer.device_id)
            and (status := self.peer_status.get(peer.device_id)) is not None
            and status.online
        ]
        if targets:
            self._broadcast_clipboard(targets, text)

    def _broadcast_clipboard(self, targets: list[Peer], text: str) -> None:
        async def broadcast() -> int:
            delivered = 0
            for peer in targets:
                try:
                    await self.client.send_clipboard(peer, text)
                    self.history.record_sent_text(peer, text)
                    delivered += 1
                except Exception:  # noqa: BLE001,S112 - one offline peer must not stop sync
                    continue
            return delivered

        self.runtime.submit(broadcast(), "clipboard_broadcast")

    # ------------------------------------------------------------ files/paths
    def open_path_safely(self, path: str) -> None:
        try:
            if Path(path).is_dir():
                reveal_in_folder(path)
            else:
                open_path(path)
        except Exception as error:  # noqa: BLE001
            self._show_error(error)

    def reveal_path_safely(self, path: str) -> None:
        try:
            reveal_in_folder(path)
        except Exception as error:  # noqa: BLE001
            self._show_error(error)

    def open_incoming_folder(self) -> None:
        folder = self.config_store.incoming_directory
        folder.mkdir(parents=True, exist_ok=True)
        try:
            reveal_in_folder(folder)
        except Exception as error:  # noqa: BLE001
            self._show_error(error)

    def _selected_history_entry(self) -> dict[str, Any] | None:
        if self.history_mode == "devices":
            return None
        selected = self.history_tree.selection()
        if len(selected) != 1:
            self._show_error(RuntimeError("Vælg en linje først."))
            return None
        entries = (
            self.history.received() if self.history_mode == "received" else self.history.sent()
        )
        try:
            return entries[int(selected[0])]
        except (ValueError, IndexError):
            return None

    def open_received_file(self) -> None:
        item = self._selected_history_entry()
        if item is None:
            return
        if item.get("kind") == "link":
            self._open_link(str(item.get("text", "")))
            return
        if item.get("kind") == "clipboard":
            self._copy_to_clipboard(str(item.get("text", "")))
            return
        path = str(item.get("path") or "")
        if not path or not Path(path).exists():
            self._show_error(FileNotFoundError(path or "Filen findes ikke længere."))
            return
        self.open_path_safely(path)

    def reveal_received_file(self) -> None:
        item = self._selected_history_entry()
        if item is None:
            return
        path = str(item.get("path") or "")
        if not path or not Path(path).exists():
            self._show_error(FileNotFoundError(path or "Filen findes ikke længere."))
            return
        self.reveal_path_safely(path)

    def save_device_name(self) -> None:
        try:
            self.config_store.device_name = self.device_name_var.get()
        except ValueError as error:
            self._show_error(error)
            return
        self.me_name.configure(text=self.config_store.device_name)
        self.toast.show("Navnet er gemt – andre enheder ser det ved næste genstart", "success")

    def choose_incoming_folder(self) -> None:
        selected = filedialog.askdirectory(
            title="Hvor skal modtagne filer gemmes?",
            initialdir=str(self.config_store.incoming_directory),
            parent=self,
        )
        if not selected:
            return
        self.config_store.incoming_directory = Path(selected)
        self.incoming_var.set(str(self.config_store.incoming_directory))

    # ----------------------------------------------------------- window / ipc
    def _handle_ipc(self, message: dict[str, Any]) -> None:
        command = message.get("cmd")
        if command == "send":
            # Explorer starts one process per selected file: collect them briefly.
            paths = [Path(str(raw)) for raw in message.get("paths") or []]
            first = not self._ipc_paths
            self._ipc_paths.extend(path for path in paths if path.exists())
            if first:
                self.after(700, self._flush_ipc_paths)
        else:
            self.show_window()

    def _flush_ipc_paths(self) -> None:
        paths = list(dict.fromkeys(self._ipc_paths))
        self._ipc_paths = []
        self.show_window()
        self._pending_send = paths
        self._flush_pending_send()

    # -------------------------------------------------- Chrome extension API
    def _api_devices(self) -> list[dict[str, Any]]:
        result = []
        for peer in list(self.peers.values()):
            if not self.config_store.is_trusted(peer.device_id):
                continue
            status = self.peer_status.get(peer.device_id)
            result.append(
                {
                    "id": peer.device_id,
                    "name": peer.name,
                    "platform": peer.platform,
                    "online": bool(status is not None and status.online),
                    "selected": peer.device_id == self.selected_id,
                }
            )
        result.sort(key=lambda item: (not item["selected"], not item["online"], item["name"]))
        return result

    async def _api_send(self, device_id: str, kind: str, value: str) -> None:
        peer = self.peers.get(device_id)
        if peer is None:
            raise RuntimeError("Enheden er ikke tilgængelig.")
        if kind == "link":
            await self.client.send_link(peer, value)
            self.history.record_sent_text(peer, value)
        elif kind == "text":
            await self.client.send_clipboard(peer, value)
            self.history.record_sent_text(peer, value)
        else:
            await self._send_download(peer, value)
        self.event_queue.put(("status", f"Sendt fra Chrome til {peer.name}"))

    async def _send_download(self, peer: Peer, url: str) -> None:
        """Download a file from the web (e.g. an image) and send it as a real file."""
        import tempfile
        import urllib.parse

        import aiohttp

        name = Path(urllib.parse.urlsplit(url).path).name or "download"
        directory = Path(tempfile.mkdtemp(prefix="h4xtor-web-"))
        target = directory / name[:120]
        timeout = aiohttp.ClientTimeout(total=120)
        async with (
            aiohttp.ClientSession(timeout=timeout, trust_env=True) as session,
            session.get(url) as response,
        ):
            response.raise_for_status()
            if "." not in target.name:
                subtype = (response.content_type or "").split("/")[-1]
                if subtype and len(subtype) < 8:
                    target = target.with_name(f"{target.name}.{subtype}")
            with target.open("wb") as output:
                async for chunk in response.content.iter_chunked(256 * 1024):
                    output.write(chunk)

        def progress(event: TransferProgress) -> None:
            self.event_queue.put(("core_event", ("", peer.name, event)))

        try:
            await self.client.send_file(peer, target, progress)
            self.history.record_sent_file(peer, target.name, target.stat().st_size, url)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    async def _api_approve(self, name: str, origin: str) -> bool:
        loop = asyncio.get_running_loop()
        decision: asyncio.Future[bool] = loop.create_future()
        self.event_queue.put(("approve_extension", (name, origin, loop, decision)))
        try:
            return await asyncio.wait_for(decision, timeout=120)
        except TimeoutError:
            return False

    def _ask_extension_approval(self, value: tuple[Any, ...]) -> None:
        name, origin, loop, decision = value
        c = self.theme.c
        px = self.theme.px
        self.show_window()
        modal = Modal(self, self.theme, "Chrome-udvidelse")
        modal.heading(
            f"{name} vil forbinde til h4xtor share",
            "Udvidelsen kan så sende faner, links, tekst og billeder fra Chrome til dine "
            "enheder. Tillad kun, hvis du selv lige har trykket Forbind i udvidelsen.",
        )
        tk.Label(modal.body, text=origin, bg=c["bg"], fg=c["faint"], font=self.theme.font(8)).pack(
            anchor="w", pady=(px(8), 0)
        )

        def answer(value: bool) -> None:
            modal.on_close = None
            modal.close()
            if not decision.done():
                loop.call_soon_threadsafe(lambda: decision.done() or decision.set_result(value))
            if value:
                self.toast.show("Chrome-udvidelsen er forbundet", "success")

        modal.on_close = lambda: answer(False)
        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(20), 0))
        Button(buttons, self.theme, "Tillad", lambda: answer(True), kind="primary").pack(
            side="right"
        )
        Button(buttons, self.theme, "Afvis", lambda: answer(False), kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        modal.present()

    def _open_link(self, url: str) -> str:
        browser = str(self.config_store.data.get("link_browser") or "chrome")
        try:
            return integration.open_url(url, browser)
        except Exception:  # noqa: BLE001
            webbrowser.open(url)
            return "default"

    def install_chrome_extension(self) -> None:
        source = Path(__file__).with_name("chrome_extension")
        if not source.is_dir():
            self._show_error(FileNotFoundError("Udvidelsen mangler i denne installation."))
            return
        target = self.config_store.path.parent / "chrome-extension"
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
        c = self.theme.c
        px = self.theme.px
        modal = Modal(self, self.theme, "Chrome-udvidelse", width=520)
        modal.heading(
            "Installér h4xtor share i Chrome",
            "Tre klik – så kan du højreklikke på sider, links, billeder og markeret tekst "
            "i Chrome og sende dem direkte til telefonen.",
        )
        for number, text in (
            ("1", "Chrome åbner siden Udvidelser – slå “Udviklertilstand” til øverst til højre"),
            ("2", "Klik “Indlæs upakket” og vælg mappen, der lige blev åbnet"),
            ("3", "Klik på h4xtor-ikonet i Chrome og tryk “Forbind”"),
        ):
            row = tk.Frame(modal.body, bg=c["bg"])
            row.pack(fill="x", pady=(px(8), 0))
            tk.Label(
                row,
                text=number,
                width=2,
                bg=c["accent_soft"],
                fg=c["accent"],
                font=self.theme.font(10, "bold"),
            ).pack(side="left", anchor="n")
            tk.Label(
                row,
                text=text,
                bg=c["bg"],
                fg=c["text"],
                font=self.theme.font(10),
                anchor="w",
                justify="left",
                wraplength=px(400),
            ).pack(side="left", padx=(px(10), 0), fill="x")
        tk.Label(
            modal.body,
            text=str(target),
            bg=c["bg"],
            fg=c["faint"],
            font=self.theme.font(8),
            anchor="w",
        ).pack(fill="x", pady=(px(12), 0))
        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(16), 0))

        def go() -> None:
            modal.close()
            self.reveal_path_safely(str(target / "manifest.json"))
            chrome = integration.find_chrome()
            if chrome:
                import subprocess

                with contextlib.suppress(OSError):
                    subprocess.Popen([chrome, "chrome://extensions/"])  # noqa: S603

        Button(buttons, self.theme, "Åbn Chrome og mappen", go, kind="primary").pack(side="right")
        Button(buttons, self.theme, "Luk", modal.close, kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        modal.present()

    def _flush_pending_send(self) -> None:
        paths, self._pending_send = self._pending_send, []
        if not paths:
            return
        target = self._drop_target_peer()
        if (
            target is not None
            and len([p for p in self.peers.values() if self.config_store.is_trusted(p.device_id)])
            == 1
        ):
            self._send_paths(target, paths)
            return
        self._choose_peer(
            lambda peer: self._send_paths(peer, paths),
            "Hvor skal det sendes hen?",
            f"{_items(len(paths))} klar til at blive sendt.",
        )

    def show_window(self) -> None:
        with contextlib.suppress(tk.TclError):
            self.deiconify()
            self.lift()
            self.focus_force()

    def close_window(self) -> None:
        if self.tray is not None and self.config_store.get_flag("close_to_tray", True):
            self.withdraw()
            if not self.config_store.get_flag("tray_hint_shown", False):
                self.config_store.set_flag("tray_hint_shown", True)
                self.tray.notify(
                    "h4xtor share kører videre i baggrunden, så du kan modtage filer. "
                    "Højreklik på ikonet ved uret for at afslutte."
                )
            return
        self.quit_app()

    def quit_app(self) -> None:
        self.close()

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            future = asyncio.run_coroutine_threadsafe(self._stop_services(), self.runtime.loop)
            future.result(timeout=4)
        except Exception:  # noqa: BLE001,S110
            pass
        self.instance.stop()
        if self.tray is not None:
            self.tray.stop()
        self.runtime.stop()
        # Cancel pending timers so Tk does not complain about dead callbacks.
        with contextlib.suppress(tk.TclError):
            for after_id in self.tk.splitlist(self.tk.call("after", "info")):
                self.after_cancel(after_id)
        with contextlib.suppress(tk.TclError):
            self.destroy()


def _items(count: int) -> str:
    return "1 element" if count == 1 else f"{count} elementer"


def _enable_high_dpi() -> None:
    if platform.system() != "Windows":
        return
    with contextlib.suppress(Exception):
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    minimized = "--minimized" in arguments
    send_paths: list[Path] = []
    if "--send" in arguments:
        index = arguments.index("--send")
        send_paths = [Path(raw) for raw in arguments[index + 1 :] if not raw.startswith("--")]
    else:
        send_paths = [Path(raw) for raw in arguments if not raw.startswith("--")]
    send_paths = [path.resolve() for path in send_paths if path.exists()]

    config = Config()
    message: dict[str, Any] = (
        {"cmd": "send", "paths": [str(path) for path in send_paths]}
        if send_paths
        else {"cmd": "show"}
    )
    if integration.send_to_running_instance(
        config.path.parent, config.port + integration.INSTANCE_PORT_OFFSET, message
    ):
        return

    _enable_high_dpi()
    app = H4xtorShareApp(start_minimized=minimized, initial_send=send_paths)
    app.mainloop()


if __name__ == "__main__":
    main()
