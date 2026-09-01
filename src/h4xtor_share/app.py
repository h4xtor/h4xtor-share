from __future__ import annotations

import asyncio
import queue
import threading
import time
import tkinter as tk
from concurrent.futures import Future
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from tkinterdnd2 import DND_FILES, TkinterDnD

from h4xtor_share import __version__
from h4xtor_share.client import PeerClient
from h4xtor_share.config import Config
from h4xtor_share.crypto import ensure_certificate, server_ssl_context
from h4xtor_share.discovery import DiscoveryService
from h4xtor_share.history import HistoryStore
from h4xtor_share.models import (
    ClipboardReceived,
    FileReceived,
    FolderReceived,
    PairingPrompt,
    Peer,
    PeerStatus,
    TransferProgress,
    signal_bars,
)
from h4xtor_share.openers import open_path, reveal_in_folder
from h4xtor_share.scanner import scan_lan as scan_lan_peers
from h4xtor_share.server import ShareServer
from h4xtor_share.transports import detect_transports
from h4xtor_share.udp import UdpDiscovery

APP_TITLE = "h4xtor-share"
VERSION = __version__

HEALTH_INTERVAL_MS = 4000
CLIPBOARD_POLL_MS = 500
CLIPBOARD_SUPPRESS_SECONDS = 3.0
SEND_CONCURRENCY = 3


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.1f} TiB"


def _format_speed(bytes_per_second: float) -> str:
    if bytes_per_second <= 0:
        return ""
    return f"{_format_bytes(bytes_per_second)}/s"


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
            try:
                value = result.result()
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


class H4xtorShareApp(TkinterDnD.Tk):
    COLORS = {
        "background": "#f4f7fb",
        "panel": "#ffffff",
        "panel_alt": "#ffffff",
        "text": "#14161c",
        "muted": "#64677d",
        "accent": "#ff8fa3",
        "accent_hover": "#f27b90",
        "accent_soft": "#ffdce3",
        "danger": "#e5484d",
        "warning": "#b7791f",
        "border": "#e7ebf1",
        "nav": "#ffffff",
        "nav_active": "#ff8fa3",
    }

    def __init__(self) -> None:
        super().__init__()
        self.config_store = Config()
        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.runtime = AsyncRuntime(self.event_queue)
        self.client = PeerClient(self.config_store)
        certificate, private_key, fingerprint = ensure_certificate(
            self.config_store.path.parent,
            self.config_store.device_name,
        )
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
        )
        self.udp_discovery = UdpDiscovery(
            self.config_store,
            fingerprint,
            ("clipboard", "files", "resume", "folders"),
            self._receive_peer,
            status_callback=lambda text: self.event_queue.put(("status", text)),
        )
        self.peers: dict[str, Peer] = {}
        self.peer_status: dict[str, PeerStatus] = {}
        self.transfer_rows: dict[str, str] = {}
        self.transfer_bars: dict[str, ttk.Progressbar] = {}
        self.transfer_speed: dict[str, tuple[float, int, float]] = {}
        self.history = HistoryStore(self.config_store.history_path)
        self._clipboard_observed = ""
        self._clipboard_suppress_text = ""
        self._clipboard_suppress_until = 0.0
        self._closing = False
        self.scan_future: Future[Any] | None = None
        self.title(f"{APP_TITLE} {VERSION}")
        self.geometry("980x700")
        self.minsize(880, 600)
        self.configure(background=self.COLORS["background"])
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_style()
        self._build_ui()
        self.after(100, self._poll_events)
        self.after(100, self._schedule_health_checks)
        self.after(1000, self._schedule_clipboard_watch)
        self.runtime.submit(self._start_services(), "services_started")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            ".",
            background=self.COLORS["panel"],
            foreground=self.COLORS["text"],
            fieldbackground=self.COLORS["panel"],
            bordercolor=self.COLORS["border"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview",
            background=self.COLORS["panel"],
            foreground=self.COLORS["text"],
            fieldbackground=self.COLORS["panel"],
            rowheight=32,
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", self.COLORS["accent_soft"])],
            foreground=[("selected", self.COLORS["text"])],
        )
        style.configure(
            "Treeview.Heading",
            background=self.COLORS["background"],
            foreground=self.COLORS["muted"],
            relief="flat",
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "TNotebook",
            background=self.COLORS["panel"],
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=self.COLORS["panel"],
            foreground=self.COLORS["muted"],
            padding=(18, 10),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.COLORS["accent_soft"])],
            foreground=[("selected", self.COLORS["accent_hover"])],
        )
        style.configure(
            "Horizontal.TProgressbar",
            background=self.COLORS["accent"],
            troughcolor=self.COLORS["background"],
            bordercolor=self.COLORS["background"],
            lightcolor=self.COLORS["accent"],
            darkcolor=self.COLORS["accent"],
        )

    NAV_ITEMS = (
        ("home", "Home"),
        ("devices", "Devices"),
        ("transfers", "Transfers"),
        ("history", "History"),
        ("clipboard", "Clipboard"),
        ("settings", "Settings"),
    )

    def _build_ui(self) -> None:
        self._build_menubar()
        header = tk.Frame(self, bg=self.COLORS["background"], padx=20, pady=16)
        header.pack(fill="x")
        tk.Label(
            header,
            text="h4xtor-share",
            bg=self.COLORS["background"],
            fg=self.COLORS["text"],
            font=("Segoe UI Semibold", 24),
        ).pack(side="left")
        tk.Label(
            header,
            text="offline peer-to-peer",
            bg=self.COLORS["background"],
            fg=self.COLORS["accent_hover"],
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(12, 0), pady=(11, 0))
        self.status_var = tk.StringVar(value="Starting local services...")
        tk.Label(
            header,
            textvariable=self.status_var,
            bg=self.COLORS["background"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(side="right", pady=(11, 0))

        self.nav_stack: dict[str, tk.Frame] = {}
        content = tk.Frame(self, bg=self.COLORS["background"])
        content.pack(fill="both", expand=True, padx=20, pady=(0, 0))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._build_home_tab(content)
        self._build_devices_tab(content)
        self._build_transfers_tab(content)
        self._build_history_tab(content)
        self._build_clipboard_tab(content)
        self._build_settings_tab(content)

        for frame in self.nav_stack.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self._build_navbar()
        self._show_view("home")

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self, tearoff=0)
        device_menu = tk.Menu(menubar, tearoff=0)
        device_menu.add_command(label="Add IP", command=self.add_manual_peer)
        device_menu.add_command(label="Scan LAN", command=self.scan_lan)
        device_menu.add_separator()
        device_menu.add_command(label="Connect", command=self.pair_selected)
        menubar.add_cascade(label="Device", menu=device_menu)

        send_menu = tk.Menu(menubar, tearoff=0)
        send_menu.add_command(label="Send clipboard", command=self.send_clipboard)
        send_menu.add_command(label="Send files", command=self.send_files)
        send_menu.add_command(label="Send folder", command=self.send_folder)
        menubar.add_cascade(label="Send", menu=send_menu)
        self.config(menu=menubar)

    def _build_navbar(self) -> None:
        bar = tk.Frame(self, bg=self.COLORS["nav"], highlightthickness=1)
        bar.configure(highlightbackground=self.COLORS["border"])
        bar.pack(fill="x", side="bottom")
        self.nav_buttons: dict[str, tk.Button] = {}
        for key, label in self.NAV_ITEMS:
            button = tk.Button(
                bar,
                text=label,
                command=lambda name=key: self._show_view(name),
                bg=self.COLORS["nav"],
                fg=self.COLORS["muted"],
                activebackground=self.COLORS["background"],
                activeforeground=self.COLORS["accent"],
                relief="flat",
                borderwidth=0,
                padx=8,
                pady=14,
                cursor="hand2",
                font=("Segoe UI Semibold", 9),
            )
            button.pack(side="left", expand=True, fill="x")
            self.nav_buttons[key] = button
        self._update_navbar()

    def _show_view(self, name: str) -> None:
        self.active_view = name
        for key, frame in self.nav_stack.items():
            if key == name:
                frame.tkraise()
        self._update_navbar()

    def _update_navbar(self) -> None:
        active = getattr(self, "active_view", "home")
        for key, button in self.nav_buttons.items():
            is_active = key == active
            button.configure(
                fg=self.COLORS["accent"] if is_active else self.COLORS["muted"],
                font=("Segoe UI Semibold", 9) if is_active else ("Segoe UI", 9),
            )

    def _button(
        self,
        parent: tk.Widget,
        text: str,
        command: Any,
        *,
        primary: bool = False,
    ) -> tk.Button:
        background = self.COLORS["accent"] if primary else self.COLORS["panel_alt"]
        foreground = "#ffffff" if primary else self.COLORS["text"]
        active = self.COLORS["accent_hover"] if primary else self.COLORS["border"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=foreground,
            activebackground=active,
            activeforeground=foreground,
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=9,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
        )

    def _card(self, parent: tk.Widget, **kwargs: Any) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=self.COLORS["panel"],
            highlightthickness=1,
            highlightbackground=self.COLORS["border"],
            highlightcolor=self.COLORS["border"],
            **kwargs,
        )

    def _build_home_tab(self, parent: tk.Frame) -> None:
        view = tk.Frame(parent, bg=self.COLORS["background"])
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        self.nav_stack["home"] = view

        card = self._card(view, padx=24, pady=24)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        tk.Label(
            card,
            text="Home",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Segoe UI Semibold", 18),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            card,
            text="Select a device and send anything, offline and peer-to-peer.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, sticky="w", pady=(4, 20))

        tk.Label(
            card,
            text="This device",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI Semibold", 10),
        ).grid(row=2, column=0, sticky="w", pady=(0, 6))
        device_row = tk.Frame(card, bg=self.COLORS["panel"])
        device_row.grid(row=3, column=0, sticky="ew", pady=(0, 20))
        self._home_device_led = tk.Label(
            device_row,
            text="●",
            bg=self.COLORS["panel"],
            fg=self.COLORS["accent_hover"],
            font=("Segoe UI", 14),
        )
        self._home_device_led.pack(side="left")
        self._home_device_name = tk.Label(
            device_row,
            text=self.config_store.device_name,
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Segoe UI Semibold", 14),
        )
        self._home_device_name.pack(side="left", padx=(10, 0))
        tk.Label(
            device_row,
            text=f"port {self.config_store.port}",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Consolas", 9),
        ).pack(side="left", padx=(12, 0), pady=(4, 0))

        tk.Label(
            card,
            text="Quick send",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI Semibold", 10),
        ).grid(row=4, column=0, sticky="w", pady=(0, 6))
        tk.Label(
            card,
            text="Select a paired device in the Devices tab, then send files or clipboard.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            wraplength=520,
            justify="left",
        ).grid(row=5, column=0, sticky="w", pady=(0, 12))
        quick = tk.Frame(card, bg=self.COLORS["panel"])
        quick.grid(row=6, column=0, sticky="w")
        self._button(quick, "Send clipboard", self.send_clipboard).pack(
            side="left", padx=(0, 8)
        )
        self._button(quick, "Send files", self.send_files).pack(side="left", padx=(0, 8))
        self._button(quick, "Send folder", self.send_folder).pack(side="left")

        card.grid_rowconfigure(7, weight=1)

    def _build_devices_tab(self, parent: tk.Frame) -> None:
        view = tk.Frame(parent, bg=self.COLORS["background"])
        view.grid_rowconfigure(1, weight=1)
        view.grid_columnconfigure(0, weight=1)
        self.nav_stack["devices"] = view

        toolbar = tk.Frame(view, bg=self.COLORS["background"])
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._button(toolbar, "Connect", self.pair_selected, primary=True).pack(
            side="left", padx=(0, 8)
        )
        self._button(toolbar, "Add IP", self.add_manual_peer).pack(side="left", padx=(0, 8))
        self._button(toolbar, "Scan LAN", self.scan_lan).pack(side="left")

        card = self._card(view, padx=12, pady=12)
        card.grid(row=1, column=0, sticky="nsew")
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        self.drop_zone = tk.Label(
            card,
            text="Drop files or folders here to send them to the selected device",
            bg=self.COLORS["background"],
            fg=self.COLORS["muted"],
            relief="flat",
            padx=12,
            pady=14,
            font=("Segoe UI Semibold", 10),
        )
        self.drop_zone.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.drop_zone.drop_target_register(DND_FILES)
        self.drop_zone.dnd_bind("<<Drop>>", self._files_dropped)

        columns = ("name", "address", "platform", "transport", "status", "signal")
        self.peer_tree = ttk.Treeview(
            card,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "name": "Device",
            "address": "Address",
            "platform": "Platform",
            "transport": "Transport",
            "status": "Status",
            "signal": "Signal",
        }
        widths = {
            "name": 230,
            "address": 170,
            "platform": 100,
            "transport": 100,
            "status": 130,
            "signal": 90,
        }
        for column in columns:
            self.peer_tree.heading(column, text=headings[column])
            self.peer_tree.column(column, width=widths[column], anchor="w")
        self.peer_tree.tag_configure("online", foreground=self.COLORS["accent_hover"])
        self.peer_tree.tag_configure("offline", foreground=self.COLORS["danger"])
        self.peer_tree.tag_configure("discovered", foreground=self.COLORS["warning"])
        self.peer_tree.tag_configure("paired", foreground=self.COLORS["text"])
        self.peer_tree.grid(row=1, column=0, sticky="nsew")
        self.peer_tree.bind("<Double-1>", self._peer_double_clicked)

    def _build_transfers_tab(self, parent: tk.Frame) -> None:
        view = tk.Frame(parent, bg=self.COLORS["background"])
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        self.nav_stack["transfers"] = view

        card = self._card(view, padx=12, pady=12)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)

        columns = ("file", "direction", "progress", "speed", "bytes")
        self.transfer_tree = ttk.Treeview(card, columns=columns, show="headings")
        for column, title, width in (
            ("file", "File", 320),
            ("direction", "Direction", 90),
            ("progress", "Progress", 90),
            ("speed", "Speed", 120),
            ("bytes", "Transferred", 200),
        ):
            self.transfer_tree.heading(column, text=title)
            self.transfer_tree.column(column, width=width, anchor="w")
        self.transfer_tree.grid(row=0, column=0, sticky="nsew")
        self.transfer_tree.bind("<Configure>", lambda _event: self._reposition_bars())

    def _reposition_bars(self) -> None:
        for row, bar in list(self.transfer_bars.items()):
            if self.transfer_tree.exists(row):
                self._place_bar(row, bar)

    def _build_history_tab(self, parent: tk.Frame) -> None:
        view = tk.Frame(parent, bg=self.COLORS["background"])
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        self.nav_stack["history"] = view

        card = self._card(view, padx=12, pady=12)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)

        sub = ttk.Notebook(card)
        sub.grid(row=0, column=0, sticky="nsew")

        sent_tab = tk.Frame(sub, bg=self.COLORS["panel"])
        received_tab = tk.Frame(sub, bg=self.COLORS["panel"])
        devices_tab = tk.Frame(sub, bg=self.COLORS["panel"])
        sub.add(sent_tab, text="Sent")
        sub.add(received_tab, text="Received")
        sub.add(devices_tab, text="Devices")

        self.history_sent_tree = self._history_tree(
            sent_tab,
            (("kind", "Type", 90), ("name", "Item", 320), ("peer", "Peer", 150),
             ("size", "Size", 100), ("ts", "Time", 150)),
        )
        self.history_received_tree = self._history_tree(
            received_tab,
            (("kind", "Type", 90), ("name", "Item", 320), ("peer", "Peer", 150),
             ("size", "Size", 100), ("ts", "Time", 150)),
        )
        self.history_devices_tree = self._history_tree(
            devices_tab,
            (("name", "Device", 170), ("ip", "IP", 140), ("os", "OS", 90),
             ("first_seen", "First seen", 150), ("last_seen", "Last seen", 150),
             ("connections", "Connects", 80)),
        )
        toolbar = tk.Frame(received_tab, bg=self.COLORS["panel"], padx=2, pady=6)
        toolbar.pack(fill="x", side="bottom")
        self._button(toolbar, "Open selected", self.open_received_file).pack(side="left")
        self._button(toolbar, "Open folder", self.reveal_received_file).pack(
            side="left", padx=(8, 0)
        )
        self._refresh_history()

    def _history_tree(
        self,
        parent: tk.Frame,
        columns: tuple[tuple[str, str, int], ...],
    ) -> ttk.Treeview:
        names = tuple(name for name, _title, _width in columns)
        tree = ttk.Treeview(parent, columns=names, show="headings")
        for name, title, width in columns:
            tree.heading(name, text=title)
            tree.column(name, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=2, pady=(2, 0))
        return tree

    def _refresh_history(self) -> None:
        for tree in (self.history_sent_tree, self.history_received_tree):
            tree.delete(*tree.get_children())
        for tree, entries in (
            (self.history_sent_tree, self.history.sent()),
            (self.history_received_tree, self.history.received()),
        ):
            for index, entry in enumerate(entries):
                tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        entry.get("kind", ""),
                        entry.get("text", ""),
                        entry.get("peer", ""),
                        _format_bytes(int(entry.get("size") or 0)),
                        entry.get("ts", ""),
                    ),
                )
        self.history_devices_tree.delete(*self.history_devices_tree.get_children())
        for entry in self.history.devices():
            self.history_devices_tree.insert(
                "",
                "end",
                values=(
                    entry.get("name", ""),
                    entry.get("ip", ""),
                    entry.get("os", ""),
                    entry.get("first_seen", ""),
                    entry.get("last_seen", ""),
                    entry.get("connections", 0),
                ),
            )

    def _build_clipboard_tab(self, parent: tk.Frame) -> None:
        view = tk.Frame(parent, bg=self.COLORS["background"])
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        self.nav_stack["clipboard"] = view

        card = self._card(view, padx=24, pady=24)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        tk.Label(
            card,
            text="Clipboard",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Segoe UI Semibold", 18),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            card,
            text="Text copied on any running connected device is broadcast to every paired device.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 10),
            wraplength=520,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 20))

        self.clipboard_apply_var = tk.BooleanVar(
            value=self.config_store.apply_received_clipboard
        )
        tk.Checkbutton(
            card,
            text="Apply received text to the system clipboard automatically",
            variable=self.clipboard_apply_var,
            command=self.save_clipboard_preference,
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            activebackground=self.COLORS["panel"],
            activeforeground=self.COLORS["text"],
            selectcolor=self.COLORS["background"],
        ).grid(row=2, column=0, sticky="w", pady=(0, 2))

        self.clipboard_sync_var = tk.BooleanVar(
            value=self.config_store.clipboard_sync_enabled
        )
        tk.Checkbutton(
            card,
            text="Broadcast new clipboard text to all paired devices automatically",
            variable=self.clipboard_sync_var,
            command=self.save_clipboard_sync_preference,
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            activebackground=self.COLORS["panel"],
            activeforeground=self.COLORS["text"],
            selectcolor=self.COLORS["background"],
        ).grid(row=3, column=0, sticky="w", pady=(0, 4))

        tk.Label(
            card,
            text="Send clipboard",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI Semibold", 10),
        ).grid(row=4, column=0, sticky="w", pady=(20, 6))
        tk.Label(
            card,
            text="Select a paired device in the Devices tab, then send the current clipboard text.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            wraplength=520,
            justify="left",
        ).grid(row=5, column=0, sticky="w", pady=(0, 8))
        self._button(card, "Send clipboard", self.send_clipboard, primary=True).grid(
            row=6, column=0, sticky="w"
        )
        card.grid_rowconfigure(7, weight=1)

    def _build_settings_tab(self, parent: tk.Frame) -> None:
        view = tk.Frame(parent, bg=self.COLORS["background"])
        view.grid_rowconfigure(0, weight=1)
        view.grid_columnconfigure(0, weight=1)
        self.nav_stack["settings"] = view

        card = self._card(view, padx=24, pady=24)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        tk.Label(
            card,
            text="This device",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Segoe UI Semibold", 16),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(
            card,
            text=f"ID: {self.config_store.device_id}",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Consolas", 9),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 16))

        tk.Label(
            card,
            text="Device name",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
        ).grid(row=2, column=0, sticky="w")
        self.device_name_var = tk.StringVar(value=self.config_store.device_name)
        tk.Entry(
            card,
            textvariable=self.device_name_var,
            bg=self.COLORS["background"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.COLORS["border"],
            highlightcolor=self.COLORS["border"],
            width=42,
        ).grid(row=3, column=0, sticky="ew", pady=(4, 12), ipady=7)
        self._button(card, "Save name", self.save_device_name).grid(
            row=3, column=1, sticky="w", padx=(10, 0), pady=(4, 12)
        )

        tk.Label(
            card,
            text="Incoming files",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
        ).grid(row=4, column=0, sticky="w")
        self.incoming_var = tk.StringVar(value=str(self.config_store.incoming_directory))
        tk.Entry(
            card,
            textvariable=self.incoming_var,
            state="readonly",
            readonlybackground=self.COLORS["background"],
            fg=self.COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.COLORS["border"],
            highlightcolor=self.COLORS["border"],
        ).grid(row=5, column=0, sticky="ew", pady=(4, 16), ipady=7)
        self._button(card, "Choose folder", self.choose_incoming_folder).grid(
            row=5, column=1, sticky="w", padx=(10, 0), pady=(4, 16)
        )

        tk.Label(
            card,
            text="Transport status",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Segoe UI Semibold", 14),
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 10))
        row = 9
        for transport in detect_transports():
            marker = "[READY]" if transport.data_path_ready else "[PLANNED]"
            marker_color = (
                self.COLORS["accent_hover"]
                if transport.data_path_ready
                else self.COLORS["warning"]
            )
            tk.Label(
                card,
                text=f"{marker} {transport.name}",
                bg=self.COLORS["panel"],
                fg=marker_color,
                font=("Segoe UI Semibold", 10),
            ).grid(row=row, column=0, sticky="nw", pady=3)
            tk.Label(
                card,
                text=transport.detail,
                bg=self.COLORS["panel"],
                fg=self.COLORS["muted"],
                wraplength=480,
                justify="left",
            ).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=3)
            row += 1
        card.grid_rowconfigure(row, weight=1)

    async def _start_services(self) -> None:
        await self.server.start()
        await asyncio.to_thread(self.discovery.start)
        await asyncio.to_thread(self.udp_discovery.start)

    async def _stop_services(self) -> None:
        await asyncio.to_thread(self.udp_discovery.stop)
        await asyncio.to_thread(self.discovery.stop)
        await self.server.stop()

    def _receive_core_event(self, event: object) -> None:
        self.event_queue.put(("core_event", event))

    def _receive_peer(self, peer: Peer) -> None:
        self.event_queue.put(("peer", peer))

    def _poll_events(self) -> None:
        if self._closing:
            return
        try:
            while True:
                tag, value = self.event_queue.get_nowait()
                self._handle_event(tag, value)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _handle_event(self, tag: str, value: Any) -> None:
        if tag == "error":
            self._show_error(value)
        elif tag == "services_started":
            self.status_var.set(f"Online locally on port {self.config_store.port}")
        elif tag == "peer":
            self._upsert_peer(value)
        elif tag == "core_event":
            self._handle_core_event(value)
        elif tag == "manual_peer":
            self._upsert_peer(value)
            self.status_var.set(f"Added {value.name}")
        elif tag == "scan_peer":
            self._upsert_peer(value)
        elif tag == "scan_progress":
            done, total = value
            self.status_var.set(f"Scanning LAN: {done}/{total}")
        elif tag == "scan_complete":
            self.scan_future = None
            self.status_var.set(f"LAN scan complete: {len(value)} device(s) found")
        elif tag == "pair_requested":
            peer, response = value
            self._prompt_for_pairing_code(peer, response)
        elif tag == "pair_confirmed":
            self._refresh_peer_rows()
            self.status_var.set("Connection established")
        elif tag == "clipboard_sent":
            self.status_var.set("Clipboard sent")
        elif tag == "files_sent":
            self._refresh_history()
            self.status_var.set("File transfer completed")
        elif tag == "peer_status":
            self._update_peer_status(value)
        elif tag == "status":
            self.status_var.set(value)
        elif tag == "health_cycle":
            pass
        elif tag == "clipboard_broadcast":
            self._refresh_history()
            self.status_var.set(f"Clipboard synced to {value} device(s)")

    def _show_error(self, error: Exception) -> None:
        self.status_var.set(str(error))
        messagebox.showerror(APP_TITLE, str(error), parent=self)

    def _handle_core_event(self, event: object) -> None:
        if isinstance(event, PairingPrompt):
            messagebox.showinfo(
                APP_TITLE,
                f"{event.peer_name} wants to connect.\n\nPairing code: {event.code}\n\n"
                "Read this code on the sending device.",
                parent=self,
            )
        elif isinstance(event, ClipboardReceived):
            if self.config_store.apply_received_clipboard:
                self.clipboard_clear()
                self.clipboard_append(event.text)
                self.update_idletasks()
                self._clipboard_observed = event.text
                self._clipboard_suppress_text = event.text
                self._clipboard_suppress_until = (
                    time.monotonic() + CLIPBOARD_SUPPRESS_SECONDS
                )
            self._record_remote_text(event, received=True)
            self.status_var.set(
                f"Clipboard received from {event.peer_name}: {len(event.text)} characters"
            )
        elif isinstance(event, FileReceived):
            self.status_var.set(f"Received {event.path.name} from {event.peer_name}")
            peer = self._peer_by_id(event.peer_id)
            if peer is not None:
                self.history.record_received_file(
                    peer,
                    event.path.name,
                    event.size,
                    str(event.path),
                )
                self._refresh_history()
        elif isinstance(event, FolderReceived):
            self.status_var.set(f"Received folder {event.path.name} from {event.peer_name}")
            peer = self._peer_by_id(event.peer_id)
            if peer is not None:
                self.history.record_received_folder(
                    peer,
                    event.path.name,
                    event.size,
                    str(event.path),
                )
                self._refresh_history()
        elif isinstance(event, TransferProgress):
            self._update_transfer(event)

    def _peer_by_id(self, device_id: str) -> Peer | None:
        return self.peers.get(device_id)

    def _record_remote_text(self, event: ClipboardReceived, received: bool) -> None:
        peer = self._peer_by_id(event.peer_id)
        if peer is None:
            return
        if received:
            self.history.record_received_text(peer, event.text)
        else:
            self.history.record_sent_text(peer, event.text)
        self._refresh_history()

    def _upsert_peer(self, peer: Peer) -> None:
        self.peers[peer.device_id] = peer
        status = self.peer_status.get(peer.device_id)
        paired = self.config_store.outbound_credentials(peer.device_id) is not None
        if status is not None and status.online:
            led, status_text, tag = "●", "Online", "online"
        elif paired:
            led, status_text, tag = "●", "Paired", "paired"
        else:
            led, status_text, tag = "○", "Discovered", "discovered"
        signal = (
            signal_bars(status.rtt_ms) if status is not None else ""
        )
        values = (
            peer.name,
            f"{peer.address}:{peer.port}",
            peer.platform,
            peer.transport,
            f"{led} {status_text}",
            signal,
        )
        if self.peer_tree.exists(peer.device_id):
            self.peer_tree.item(peer.device_id, values=values, tags=(tag,))
        else:
            self.peer_tree.insert("", "end", iid=peer.device_id, values=values, tags=(tag,))

    def _update_peer_status(self, status: PeerStatus) -> None:
        previous = self.peer_status.get(status.device_id)
        self.peer_status[status.device_id] = status
        peer = self.peers.get(status.device_id)
        if peer is None:
            return
        if previous is None or previous.online != status.online:
            self.history.record_connection(peer, status.online, status.rtt_ms)
        self._upsert_peer(peer)

    async def _check_peer_health(self) -> None:
        peers = list(self.peers.values())
        if not peers:
            return
        results = await asyncio.gather(
            *(self._probe_peer(peer) for peer in peers),
            return_exceptions=True,
        )
        for peer, result in zip(peers, results, strict=True):
            if isinstance(result, Exception):
                self.event_queue.put(
                    ("peer_status", PeerStatus(peer.device_id, False, None))
                )
            else:
                self.event_queue.put(
                    ("peer_status", PeerStatus(peer.device_id, True, result))
                )

    async def _probe_peer(self, peer: Peer) -> float:
        try:
            return await self.client.ping(peer)
        except Exception:
            raise

    def _schedule_health_checks(self) -> None:
        if self._closing:
            return
        self.runtime.submit(self._check_peer_health(), "health_cycle")
        self.after(HEALTH_INTERVAL_MS, self._schedule_health_checks)

    def _refresh_peer_rows(self) -> None:
        for peer in self.peers.values():
            self._upsert_peer(peer)

    def selected_peer(self) -> Peer:
        selected = self.peer_tree.selection()
        if len(selected) != 1:
            raise RuntimeError("Select exactly one device.")
        return self.peers[selected[0]]

    def add_manual_peer(self) -> None:
        address = simpledialog.askstring(
            APP_TITLE,
            "Peer IP address:",
            parent=self,
        )
        if not address:
            return
        port = simpledialog.askinteger(
            APP_TITLE,
            "Peer port:",
            initialvalue=self.config_store.port,
            minvalue=1,
            maxvalue=65535,
            parent=self,
        )
        if port is None:
            return
        self.runtime.submit(
            self.client.get_info(address.strip(), port),
            "manual_peer",
        )

    def scan_lan(self) -> None:
        if self.scan_future is not None and not self.scan_future.done():
            self.status_var.set("LAN scan is already running")
            return
        self.status_var.set("Scanning local /24 network...")
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

    def pair_selected(self) -> None:
        try:
            peer = self.selected_peer()
        except RuntimeError as error:
            self._show_error(error)
            return
        self.status_var.set(f"Connecting to {peer.name}...")
        async def request() -> tuple[Peer, dict[str, Any]]:
            return peer, await self.client.request_pairing(peer)

        self.runtime.submit(request(), "pair_requested")

    def _prompt_for_pairing_code(
        self,
        peer: Peer,
        response: dict[str, Any],
    ) -> None:
        code = simpledialog.askstring(
            APP_TITLE,
            f"Enter the six-digit code shown on {peer.name}:",
            parent=self,
        )
        if code is None:
            return
        if len(code.strip()) != 6 or not code.strip().isdigit():
            self._show_error(ValueError("Pairing code must contain six digits."))
            return
        self.runtime.submit(
            self.client.confirm_pairing(
                peer,
                str(response["pairing_id"]),
                code.strip(),
            ),
            "pair_confirmed",
        )

    def send_clipboard(self) -> None:
        try:
            peer = self.selected_peer()
            text = self.clipboard_get()
        except (RuntimeError, tk.TclError) as error:
            self._show_error(RuntimeError(f"Cannot send clipboard: {error}"))
            return
        self.status_var.set(f"Sending clipboard to {peer.name}...")
        self._clipboard_observed = text
        self.history.record_sent_text(peer, text)
        self._refresh_history()
        self.runtime.submit(
            self.client.send_clipboard(peer, text),
            "clipboard_sent",
        )

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
        self._clipboard_observed = text
        targets = [
            peer
            for peer in self.peers.values()
            if self.config_store.outbound_credentials(peer.device_id) is not None
        ]
        if not targets:
            return
        self._broadcast_clipboard(targets, text)

    def _broadcast_clipboard(self, targets: list[Peer], text: str) -> None:

        async def broadcast() -> None:
            delivered = 0
            for peer in targets:
                try:
                    await self.client.send_clipboard(peer, text)
                    self.history.record_sent_text(peer, text)
                    delivered += 1
                except Exception:
                    pass
            if delivered:
                self.event_queue.put(("clipboard_broadcast", delivered))

        self.status_var.set(f"Syncing clipboard to {len(targets)} device(s)...")
        self.runtime.submit(broadcast(), "clipboard_broadcast")

    def send_files(self) -> None:
        try:
            peer = self.selected_peer()
        except RuntimeError as error:
            self._show_error(error)
            return
        paths = filedialog.askopenfilenames(
            title="Choose files to send",
            parent=self,
        )
        if not paths:
            return

        self._send_paths(peer, [Path(raw_path) for raw_path in paths])

    def send_folder(self) -> None:
        try:
            peer = self.selected_peer()
        except RuntimeError as error:
            self._show_error(error)
            return
        if not peer.supports_folders:
            self._show_error(
                RuntimeError(f"{peer.name} does not support folder transfers yet.")
            )
            return
        path = filedialog.askdirectory(
            title="Choose folder to send",
            initialdir=str(Path.home()),
            parent=self,
        )
        if not path:
            return
        self._send_paths(peer, [Path(path)])

    def _files_dropped(self, event: Any) -> str:
        try:
            peer = self.selected_peer()
        except RuntimeError as error:
            self._show_error(error)
            return "break"
        paths = [Path(raw_path) for raw_path in self.tk.splitlist(event.data)]
        files = [path for path in paths if path.is_file()]
        folders = [path for path in paths if path.is_dir()]
        if not files and not folders:
            self._show_error(ValueError("The drop did not contain any files."))
            return "break"
        self._send_paths(peer, files + folders)
        return "break"

    def _send_paths(self, peer: Peer, paths: list[Path]) -> None:
        files = [path for path in paths if path.is_file()]
        folders = [path for path in paths if path.is_dir()]
        unsupported = [path for path in folders if not peer.supports_folders]
        if unsupported:
            names = ", ".join(path.name for path in unsupported[:3])
            self._show_error(
                RuntimeError(
                    f"{peer.name} does not support folder transfers yet: {names}"
                )
            )
            folders = [path for path in folders if peer.supports_folders]
        if not files and not folders:
            return

        def progress_callback(transfer_progress: TransferProgress) -> None:
            self.event_queue.put(("core_event", transfer_progress))

        def folder_size(path: Path) -> int:
            return sum(
                child.stat().st_size for child in path.rglob("*") if child.is_file()
            )

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
                        self.history.record_sent_file(
                            peer, path.name, size, str(path)
                        )

            await asyncio.gather(*(send_one(path) for path in files + folders))

        count = len(files) + len(folders)
        self.status_var.set(f"Sending {count} item(s) to {peer.name}...")
        self.runtime.submit(send_all(), "files_sent")

    def _update_transfer(self, progress: TransferProgress) -> None:
        now = time.monotonic()
        previous = self.transfer_speed.get(progress.transfer_id)
        if previous:
            last_time, last_sent, smoothed = previous
            elapsed = now - last_time
            if elapsed > 0:
                instantaneous = (progress.sent - last_sent) / elapsed
                smoothed = (
                    instantaneous
                    if smoothed <= 0
                    else smoothed * 0.7 + instantaneous * 0.3
                )
        else:
            smoothed = 0.0
        self.transfer_speed[progress.transfer_id] = (now, progress.sent, smoothed)

        percent = f"{progress.percent:.0f}%"
        speed = _format_speed(smoothed)
        values = (
            progress.file_name,
            progress.direction,
            percent,
            speed,
            f"{progress.sent:,} / {progress.total:,} bytes",
        )
        row = self.transfer_rows.get(progress.transfer_id)
        if row and self.transfer_tree.exists(row):
            self.transfer_tree.item(row, values=values)
            bar = self.transfer_bars.get(row)
            if bar is not None:
                bar.configure(
                    maximum=max(1, progress.total),
                    value=progress.sent,
                )
                self._place_bar(row, bar)
            return
        row = self.transfer_tree.insert("", "end", values=values)
        self.transfer_rows[progress.transfer_id] = row
        bar = ttk.Progressbar(
            self.transfer_tree,
            orient="horizontal",
            mode="determinate",
            maximum=max(1, progress.total),
            value=progress.sent,
        )
        self.transfer_bars[row] = bar
        self._place_bar(row, bar)

    def _place_bar(self, row: str, bar: ttk.Progressbar) -> None:
        self.transfer_tree.update_idletasks()
        bounds = self.transfer_tree.bbox(row, "progress")
        if not bounds or len(bounds) < 4:
            return
        x, y, width, height = bounds
        bar.place(x=x, y=y, width=width - 4, height=height)

    def _peer_double_clicked(self, _event: Any) -> None:
        if self.selected_peer_if_any() is not None:
            self.pair_selected()

    def selected_peer_if_any(self) -> Peer | None:
        selected = self.peer_tree.selection()
        if len(selected) != 1:
            return None
        return self.peers.get(selected[0])

    def open_received_file(self) -> None:
        selected = self.history_received_tree.selection()
        if len(selected) != 1:
            self._show_error(RuntimeError("Select exactly one received file."))
            return
        entry = self.history.received()[int(selected[0])]
        path = entry.get("path") or ""
        if not path or not Path(path).exists():
            self._show_error(FileNotFoundError(path or "Missing file path in history."))
            return
        try:
            if Path(path).is_dir() or entry.get("kind") == "folder":
                reveal_in_folder(path)
            else:
                open_path(path)
        except Exception as error:
            self._show_error(error)

    def reveal_received_file(self) -> None:
        selected = self.history_received_tree.selection()
        if len(selected) != 1:
            self._show_error(RuntimeError("Select exactly one received file."))
            return
        entry = self.history.received()[int(selected[0])]
        path = entry.get("path") or ""
        if not path or not Path(path).exists():
            self._show_error(FileNotFoundError(path or "Missing file path in history."))
            return
        try:
            reveal_in_folder(path)
        except Exception as error:
            self._show_error(error)

    def save_device_name(self) -> None:
        try:
            self.config_store.device_name = self.device_name_var.get()
        except ValueError as error:
            self._show_error(error)
            return
        self.status_var.set("Device name saved; restart to update discovery")

    def choose_incoming_folder(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose incoming files folder",
            initialdir=str(self.config_store.incoming_directory),
            parent=self,
        )
        if not selected:
            return
        self.config_store.incoming_directory = Path(selected)
        self.incoming_var.set(str(self.config_store.incoming_directory))

    def save_clipboard_preference(self) -> None:
        self.config_store.apply_received_clipboard = self.clipboard_apply_var.get()

    def save_clipboard_sync_preference(self) -> None:
        self.config_store.clipboard_sync_enabled = self.clipboard_sync_var.get()

    def close(self) -> None:
        self._closing = True
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._stop_services(),
                self.runtime.loop,
            )
            future.result(timeout=4)
        except Exception:
            pass
        self.runtime.stop()
        self.destroy()


def main() -> None:
    app = H4xtorShareApp()
    app.mainloop()


if __name__ == "__main__":
    main()
