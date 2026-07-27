from __future__ import annotations

import asyncio
import queue
import threading
import tkinter as tk
from concurrent.futures import Future
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from h4xtor_share.client import PeerClient
from h4xtor_share.config import Config
from h4xtor_share.crypto import ensure_certificate, server_ssl_context
from h4xtor_share.discovery import DiscoveryService
from h4xtor_share.models import (
    ClipboardReceived,
    FileReceived,
    PairingPrompt,
    Peer,
    TransferProgress,
)
from h4xtor_share.server import ShareServer
from h4xtor_share.transports import detect_transports

APP_TITLE = "h4xtor-share"
VERSION = "0.1.0"


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
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)


class H4xtorShareApp(tk.Tk):
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
        self.transfer_rows: dict[str, str] = {}
        self.title(f"{APP_TITLE} {VERSION}")
        self.geometry("920x650")
        self.minsize(820, 560)
        self.configure(background=self.COLORS["background"])
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_style()
        self._build_ui()
        self.after(100, self._poll_events)
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
        settings_tab = tk.Frame(notebook, bg=self.COLORS["panel"])
        notebook.add(devices_tab, text="Devices")
        notebook.add(transfers_tab, text="Transfers")
        notebook.add(settings_tab, text="Settings")

        self._build_devices_tab(devices_tab)
        self._build_transfers_tab(transfers_tab)
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
        self._button(toolbar, "Pair", self.pair_selected, primary=True).pack(
            side="left", padx=(0, 8)
        )
        self._button(toolbar, "Send clipboard", self.send_clipboard).pack(
            side="left", padx=(0, 8)
        )
        self._button(toolbar, "Send files", self.send_files).pack(side="left")

        columns = ("name", "address", "platform", "transport", "trust")
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
            "trust": "Status",
        }
        widths = {
            "name": 230,
            "address": 170,
            "platform": 110,
            "transport": 110,
            "trust": 110,
        }
        for column in columns:
            self.peer_tree.heading(column, text=headings[column])
            self.peer_tree.column(column, width=widths[column], anchor="w")
        self.peer_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _build_transfers_tab(self, parent: tk.Frame) -> None:
        columns = ("file", "direction", "progress", "bytes")
        self.transfer_tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column, title, width in (
            ("file", "File", 360),
            ("direction", "Direction", 100),
            ("progress", "Progress", 120),
            ("bytes", "Transferred", 200),
        ):
            self.transfer_tree.heading(column, text=title)
            self.transfer_tree.column(column, width=width, anchor="w")
        self.transfer_tree.pack(fill="both", expand=True, padx=12, pady=12)

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
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 20))

        tk.Label(
            container,
            text="Transport status",
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            font=("Segoe UI Semibold", 14),
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 10))
        row = 8
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
        elif tag == "pair_requested":
            peer, response = value
            self._prompt_for_pairing_code(peer, response)
        elif tag == "pair_confirmed":
            self._refresh_peer_rows()
            self.status_var.set("Pairing completed")
        elif tag == "clipboard_sent":
            self.status_var.set("Clipboard sent")
        elif tag == "files_sent":
            self.status_var.set("File transfer completed")

    def _show_error(self, error: Exception) -> None:
        self.status_var.set(str(error))
        messagebox.showerror(APP_TITLE, str(error), parent=self)

    def _handle_core_event(self, event: object) -> None:
        if isinstance(event, PairingPrompt):
            messagebox.showinfo(
                APP_TITLE,
                f"{event.peer_name} wants to pair.\n\nPairing code: {event.code}\n\n"
                "Read this code on the sending device.",
                parent=self,
            )
        elif isinstance(event, ClipboardReceived):
            if self.config_store.apply_received_clipboard:
                self.clipboard_clear()
                self.clipboard_append(event.text)
                self.update_idletasks()
            self.status_var.set(
                f"Clipboard received from {event.peer_name}: {len(event.text)} characters"
            )
        elif isinstance(event, FileReceived):
            self.status_var.set(f"Received {event.path.name} from {event.peer_name}")
        elif isinstance(event, TransferProgress):
            self._update_transfer(event)

    def _upsert_peer(self, peer: Peer) -> None:
        self.peers[peer.device_id] = peer
        trust = (
            "Paired"
            if self.config_store.outbound_credentials(peer.device_id)
            else "Not paired"
        )
        values = (
            peer.name,
            f"{peer.address}:{peer.port}",
            peer.platform,
            peer.transport,
            trust,
        )
        if self.peer_tree.exists(peer.device_id):
            self.peer_tree.item(peer.device_id, values=values)
        else:
            self.peer_tree.insert("", "end", iid=peer.device_id, values=values)

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

    def pair_selected(self) -> None:
        try:
            peer = self.selected_peer()
        except RuntimeError as error:
            self._show_error(error)
            return
        self.status_var.set(f"Requesting pairing with {peer.name}...")
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
        self.runtime.submit(
            self.client.send_clipboard(peer, text),
            "clipboard_sent",
        )

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

        async def send_all() -> None:
            for raw_path in paths:
                await self.client.send_file(
                    peer,
                    Path(raw_path),
                    lambda progress: self.event_queue.put(("core_event", progress)),
                )

        self.status_var.set(f"Sending {len(paths)} file(s) to {peer.name}...")
        self.runtime.submit(send_all(), "files_sent")

    def _update_transfer(self, progress: TransferProgress) -> None:
        values = (
            progress.file_name,
            progress.direction,
            f"{progress.percent:.1f}%",
            f"{progress.sent:,} / {progress.total:,} bytes",
        )
        row = self.transfer_rows.get(progress.transfer_id)
        if row and self.transfer_tree.exists(row):
            self.transfer_tree.item(row, values=values)
        else:
            row = self.transfer_tree.insert("", "end", values=values)
            self.transfer_rows[progress.transfer_id] = row

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

    def close(self) -> None:
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
