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

APP_TITLE = "h4xtor-share"
VERSION = __version__

HEALTH_INTERVAL_MS = 4000
CLIPBOARD_POLL_MS = 500
CLIPBOARD_SUPPRESS_SECONDS = 3.0


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.1f} TiB"


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
        "background": "#0b0f14",
        "panel": "#121923",
        "panel_alt": "#182230",
        "text": "#eaf2fb",
        "muted": "#93a4b8",
        "accent": "#00d1b2",
        "accent_hover": "#00b89c",
        "danger": "#ff5c70",
        "warning": "#f6c344",
        "border": "#263548",
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
        self.peers: dict[str, Peer] = {}
        self.peer_status: dict[str, PeerStatus] = {}
        self.transfer_rows: dict[str, str] = {}
        self.transfer_bars: dict[str, ttk.Progressbar] = {}
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
            fieldbackground=self.COLORS["panel_alt"],
            bordercolor=self.COLORS["border"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview",
            background=self.COLORS["panel_alt"],
            foreground=self.COLORS["text"],
            fieldbackground=self.COLORS["panel_alt"],
            rowheight=30,
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", self.COLORS["accent"])],
            foreground=[("selected", "#06110f")],
        )
        style.configure(
            "Treeview.Heading",
            background=self.COLORS["panel"],
            foreground=self.COLORS["muted"],
            relief="flat",
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "TNotebook",
            background=self.COLORS["background"],
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=self.COLORS["panel"],
            foreground=self.COLORS["muted"],
            padding=(18, 10),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.COLORS["accent"])],
            foreground=[("selected", "#06110f")],
        )

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=self.COLORS["background"], padx=18, pady=16)
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
            fg=self.COLORS["accent"],
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(12, 0), pady=(10, 0))
        self.status_var = tk.StringVar(value="Starting local services...")
        tk.Label(
            header,
            textvariable=self.status_var,
            bg=self.COLORS["background"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(side="right", pady=(9, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        devices_tab = tk.Frame(notebook, bg=self.COLORS["panel"])
        transfers_tab = tk.Frame(notebook, bg=self.COLORS["panel"])
        history_tab = tk.Frame(notebook, bg=self.COLORS["panel"])
        settings_tab = tk.Frame(notebook, bg=self.COLORS["panel"])
        notebook.add(devices_tab, text="Devices")
        notebook.add(transfers_tab, text="Transfers")
        notebook.add(history_tab, text="History")
        notebook.add(settings_tab, text="Settings")

        self._build_devices_tab(devices_tab)
        self._build_transfers_tab(transfers_tab)
        self._build_history_tab(history_tab)
        self._build_settings_tab(settings_tab)

    def _button(
        self,
        parent: tk.Widget,
        text: str,
        command: Any,
        *,
        primary: bool = False,
    ) -> tk.Button:
        background = self.COLORS["accent"] if primary else self.COLORS["panel_alt"]
        foreground = "#06110f" if primary else self.COLORS["text"]
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

    def _build_devices_tab(self, parent: tk.Frame) -> None:
        toolbar = tk.Frame(parent, bg=self.COLORS["panel"], padx=12, pady=12)
        toolbar.pack(fill="x")
        self._button(toolbar, "Add IP", self.add_manual_peer).pack(side="left", padx=(0, 8))
        self._button(toolbar, "Scan LAN", self.scan_lan).pack(side="left", padx=(0, 8))
        self._button(toolbar, "Connect", self.pair_selected, primary=True).pack(
            side="left", padx=(0, 8)
        )
        self._button(toolbar, "Send clipboard", self.send_clipboard).pack(
            side="left", padx=(0, 8)
        )
        self._button(toolbar, "Send files", self.send_files).pack(side="left")

        self.drop_zone = tk.Label(
            parent,
            text="Drop files here to send them to the selected device",
            bg=self.COLORS["panel_alt"],
            fg=self.COLORS["muted"],
            relief="flat",
            padx=12,
            pady=14,
            font=("Segoe UI Semibold", 10),
        )
        self.drop_zone.pack(fill="x", padx=12, pady=(0, 12))
        self.drop_zone.drop_target_register(DND_FILES)
        self.drop_zone.dnd_bind("<<Drop>>", self._files_dropped)

        columns = ("name", "address", "platform", "transport", "status", "signal")
        self.peer_tree = ttk.Treeview(
            parent,
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
        self.peer_tree.tag_configure("online", foreground=self.COLORS["accent"])
        self.peer_tree.tag_configure("offline", foreground=self.COLORS["danger"])
        self.peer_tree.tag_configure("discovered", foreground=self.COLORS["warning"])
        self.peer_tree.tag_configure("paired", foreground=self.COLORS["text"])
        self.peer_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.peer_tree.bind("<Double-1>", self._peer_double_clicked)

    def _build_transfers_tab(self, parent: tk.Frame) -> None:
        columns = ("file", "direction", "progress", "bytes")
        self.transfer_tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column, title, width in (
            ("file", "File", 360),
            ("direction", "Direction", 90),
            ("progress", "Progress", 150),
            ("bytes", "Transferred", 200),
        ):
            self.transfer_tree.heading(column, text=title)
            self.transfer_tree.column(column, width=width, anchor="w")
        self.transfer_tree.pack(fill="both", expand=True, padx=12, pady=12)
        self.transfer_tree.bind("<Configure>", lambda _event: self._reposition_bars())

    def _reposition_bars(self) -> None:
        for row, bar in list(self.transfer_bars.items()):
            if self.transfer_tree.exists(row):
                self._place_bar(row, bar)

    def _build_history_tab(self, parent: tk.Frame) -> None:
        sub = ttk.Notebook(parent)
        sub.pack(fill="both", expand=True, padx=12, pady=12)

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

    def _build_settings_tab(self, parent: tk.Frame) -> None:
        container = tk.Frame(parent, bg=self.COLORS["panel"], padx=20, pady=20)
        container.pack(fill="both", expand=True)
        tk.Label(
            container,
            text="This device",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Segoe UI Semibold", 16),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(
            container,
            text=f"ID: {self.config_store.device_id}",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Consolas", 9),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 16))

        tk.Label(
            container,
            text="Device name",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
        ).grid(row=2, column=0, sticky="w")
        self.device_name_var = tk.StringVar(value=self.config_store.device_name)
        tk.Entry(
            container,
            textvariable=self.device_name_var,
            bg=self.COLORS["panel_alt"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            width=42,
        ).grid(row=3, column=0, sticky="ew", pady=(4, 12), ipady=7)
        self._button(container, "Save name", self.save_device_name).grid(
            row=3, column=1, sticky="w", padx=(10, 0), pady=(4, 12)
        )

        tk.Label(
            container,
            text="Incoming files",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
        ).grid(row=4, column=0, sticky="w")
        self.incoming_var = tk.StringVar(value=str(self.config_store.incoming_directory))
        tk.Entry(
            container,
            textvariable=self.incoming_var,
            state="readonly",
            readonlybackground=self.COLORS["panel_alt"],
            fg=self.COLORS["text"],
            relief="flat",
        ).grid(row=5, column=0, sticky="ew", pady=(4, 16), ipady=7)
        self._button(container, "Choose folder", self.choose_incoming_folder).grid(
            row=5, column=1, sticky="w", padx=(10, 0), pady=(4, 16)
        )

        self.clipboard_apply_var = tk.BooleanVar(
            value=self.config_store.apply_received_clipboard
        )
        tk.Checkbutton(
            container,
            text="Apply received text to the system clipboard automatically",
            variable=self.clipboard_apply_var,
            command=self.save_clipboard_preference,
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            activebackground=self.COLORS["panel"],
            activeforeground=self.COLORS["text"],
            selectcolor=self.COLORS["panel_alt"],
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 2))

        self.clipboard_sync_var = tk.BooleanVar(
            value=self.config_store.clipboard_sync_enabled
        )
        tk.Checkbutton(
            container,
            text="Broadcast new clipboard text to all paired devices automatically",
            variable=self.clipboard_sync_var,
            command=self.save_clipboard_sync_preference,
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            activebackground=self.COLORS["panel"],
            activeforeground=self.COLORS["text"],
            selectcolor=self.COLORS["panel_alt"],
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 20))

        tk.Label(
            container,
            text="Transport status",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Segoe UI Semibold", 14),
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 10))
        row = 9
        for transport in detect_transports():
            marker = "[READY]" if transport.data_path_ready else "[PLANNED]"
            marker_color = (
                self.COLORS["accent"]
                if transport.data_path_ready
                else self.COLORS["warning"]
            )
            tk.Label(
                container,
                text=f"{marker} {transport.name}",
                bg=self.COLORS["panel"],
                fg=marker_color,
                font=("Segoe UI Semibold", 10),
            ).grid(row=row, column=0, sticky="nw", pady=3)
            tk.Label(
                container,
                text=transport.detail,
                bg=self.COLORS["panel"],
                fg=self.COLORS["muted"],
                wraplength=480,
                justify="left",
            ).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=3)
            row += 1
        container.columnconfigure(0, weight=1)

    async def _start_services(self) -> None:
        await self.server.start()
        await asyncio.to_thread(self.discovery.start)

    async def _stop_services(self) -> None:
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

    def _files_dropped(self, event: Any) -> str:
        try:
            peer = self.selected_peer()
        except RuntimeError as error:
            self._show_error(error)
            return "break"
        paths = [Path(raw_path) for raw_path in self.tk.splitlist(event.data)]
        files = [path for path in paths if path.is_file()]
        if not files:
            self._show_error(ValueError("The drop did not contain any files."))
            return "break"
        self._send_paths(peer, files)
        return "break"

    def _send_paths(self, peer: Peer, paths: list[Path]) -> None:

        async def send_all() -> None:
            for path in paths:
                size = path.stat().st_size
                await self.client.send_file(
                    peer,
                    path,
                    lambda progress: self.event_queue.put(("core_event", progress)),
                )
                self.history.record_sent_file(peer, path.name, size, str(path))

        self.status_var.set(f"Sending {len(paths)} file(s) to {peer.name}...")
        self.runtime.submit(send_all(), "files_sent")

    def _update_transfer(self, progress: TransferProgress) -> None:
        row = self.transfer_rows.get(progress.transfer_id)
        if row and self.transfer_tree.exists(row):
            self.transfer_tree.item(
                row,
                values=(
                    progress.file_name,
                    progress.direction,
                    "",
                    f"{progress.sent:,} / {progress.total:,} bytes",
                ),
            )
            bar = self.transfer_bars.get(row)
            if bar is not None:
                bar.configure(
                    maximum=max(1, progress.total),
                    value=progress.sent,
                )
                self._place_bar(row, bar)
            return
        row = self.transfer_tree.insert(
            "",
            "end",
            values=(progress.file_name, progress.direction, "", ""),
        )
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
        if not path or not Path(path).is_file():
            self._show_error(FileNotFoundError(path or "Missing file path in history."))
            return
        try:
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
        if not path or not Path(path).is_file():
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
