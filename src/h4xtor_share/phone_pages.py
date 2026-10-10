"""Phone pages of the desktop app: notifications, SMS, remote control and Google Drive.

These are mixed into ``H4xtorShareApp`` (they use its theme, pages, toast, peers and
client). Network calls always run on the asyncio runtime through ``_phone_call``; the
result comes back on the Tk thread as ``done(ok, value_or_error)``.
"""

from __future__ import annotations

import base64
import time
import tkinter as tk
import webbrowser
from collections.abc import Callable, Coroutine
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import Any

from h4xtor_share.gdrive import SETUP_HELP, GoogleDrive, GoogleDriveError
from h4xtor_share.models import NotificationReceived, NotificationRemoved, Peer, SmsReceived
from h4xtor_share.ui_kit import Button, Card, Modal, ScrollFrame, Slider, entry

MAX_NOTIFICATIONS = 200
SCREENSHOT_WAIT_SECONDS = 180
UPDATE_HINT = "Telefonen skal opdateres"
IMAGE_TYPES = [("Billeder", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("Alle filer", "*.*")]


def ago(millis: int, now: float | None = None) -> str:
    """Short Danish relative time, e.g. "nu", "5 min siden", "2 t siden"."""
    if not millis:
        return ""
    seconds = int((now if now is not None else time.time()) - millis / 1000)
    if seconds < 45:
        return "nu"
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min siden"
    if seconds < 86400:
        return f"{seconds // 3600} t siden"
    return datetime.fromtimestamp(millis / 1000).strftime("%d.%m. %H:%M")


def clock(millis: int) -> str:
    """Time of day for today, date otherwise (SMS lists)."""
    if not millis:
        return ""
    moment = datetime.fromtimestamp(millis / 1000)
    if moment.date() == datetime.now().date():
        return moment.strftime("%H:%M")
    return moment.strftime("%d.%m.")


class NotifEntry:
    """One phone notification and the widgets that show it."""

    def __init__(self, event: NotificationReceived) -> None:
        self.peer_id = event.peer_id
        self.peer_name = event.peer_name
        self.key = event.key
        self.package = event.package
        self.app = event.app
        self.title = event.title
        self.text = event.text
        self.time = event.time or int(time.time() * 1000)
        self.icon_png = event.icon_png
        self.can_reply = event.can_reply
        self.can_dismiss = event.can_dismiss
        self.card: Card | None = None
        self.time_label: tk.Label | None = None
        self.reply_row: tk.Frame | None = None
        self.photo: tk.PhotoImage | None = None
        self.content: tk.Frame | None = None


class PhonePagesMixin:
    # Everything below relies on H4xtorShareApp attributes (theme, pages, toast, ...).
    # ------------------------------------------------------------------ plumbing
    def _init_phone_state(self) -> None:
        self.notif_entries: list[NotifEntry] = []
        self.notif_unread = 0
        self.sms_peer_id: str | None = None
        self.sms_threads: dict[str, list[dict[str, Any]]] = {}
        self.sms_messages: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.sms_current: dict[str, str] | None = None
        self.sms_unread = 0
        self.sms_pending_address = ""
        self.remote_peer_id: str | None = None
        self.pending_screenshot: tuple[str, float] | None = None
        self.gdrive = GoogleDrive(self.config_store)
        self.drive_busy = ""

    def _phone_call(
        self, coroutine: Coroutine[Any, Any, Any], done: Callable[[bool, Any], None]
    ) -> None:
        async def run() -> tuple[Any, bool, Any]:
            try:
                return done, True, await coroutine
            except Exception as error:  # noqa: BLE001 - reported on the Tk thread
                return done, False, error

        self.runtime.submit(run(), "phone_call")

    def _phone_error(self, error: BaseException) -> str:
        from h4xtor_share.app import friendly_error

        return friendly_error(error, self.peers.values())

    def _capable_peers(self, capability: str) -> list[Peer]:
        """Paired peers with ``capability`` (every paired peer when it is empty)."""
        peers = [p for p in self._trusted_peers() if not capability or p.supports(capability)]
        return sorted(peers, key=lambda p: p.name.lower())

    def _fill_picker(
        self,
        host: tk.Frame,
        capability: str | None,
        current_id: str | None,
        pick: Callable[[Peer], None],
    ) -> list[Peer]:
        """Device chips for peers with ``capability``; says so when others need an update."""
        c = self.theme.c
        px = self.theme.px
        for child in host.winfo_children():
            child.destroy()
        capable = self._capable_peers(capability or "")
        if len(capable) > 1:
            for peer in capable:
                Button(
                    host,
                    self.theme,
                    peer.name,
                    lambda p=peer: pick(p),
                    size="sm",
                    kind="soft" if peer.device_id == current_id else "ghost",
                ).pack(side="left", padx=(0, px(6)))
        elif capable:
            tk.Label(
                host,
                text=f"Enhed: {capable[0].name}",
                bg=c["bg"],
                fg=c["muted"],
                font=self.theme.font(10),
            ).pack(side="left")
        lacking = len(self._trusted_peers()) - len(capable)
        if lacking > 0:
            who = "enhed" if lacking == 1 else "enheder"
            tk.Label(
                host,
                text=f"{lacking} {who} kan ikke dette endnu – {UPDATE_HINT}.",
                bg=c["bg"],
                fg=c["faint"],
                font=self.theme.font(9),
            ).pack(side="left", padx=(px(10), 0))
        return capable

    def _pick_current(self, capable: list[Peer], current_id: str | None) -> Peer | None:
        for peer in capable:
            if peer.device_id == current_id:
                return peer
        online = [
            p for p in capable if (s := self.peer_status.get(p.device_id)) is not None and s.online
        ]
        return (online or capable or [None])[0]

    def _notice(self, parent: tk.Misc, text: str, tone: str = "muted") -> tk.Label:
        c = self.theme.c
        return tk.Label(
            parent,
            text=text,
            bg=c["bg"],
            fg=c["danger"] if tone == "danger" else c["muted"],
            font=self.theme.font(10),
            anchor="w",
            justify="left",
            wraplength=self.theme.px(560),
        )

    def _autowrap(self, label: tk.Label, container: tk.Misc, margin: int = 0) -> None:
        container.bind(
            "<Configure>",
            lambda e: label.configure(wraplength=max(140, e.width - margin)),
            add="+",
        )

    def _set_nav_badge(self, key: str, count: int) -> None:
        badge = self.nav_badges.get(key)
        if badge is not None:
            badge.configure(text="" if count <= 0 else ("9+" if count > 9 else str(count)))

    def _phone_page_shown(self, name: str) -> None:
        """Called by ``show_page`` for the phone pages."""
        if name == "notifications":
            self.notif_unread = 0
            self._set_nav_badge("notifications", 0)
            self._notif_refresh_times()
        elif name == "sms":
            self.sms_unread = 0
            self._set_nav_badge("sms", 0)
            self._sms_open()
        elif name == "remote":
            self._remote_open()

    def _handle_phone_core_event(self, event: object) -> bool:
        if isinstance(event, NotificationReceived):
            self._notif_received(event)
        elif isinstance(event, NotificationRemoved):
            self._notif_removed(event)
        elif isinstance(event, SmsReceived):
            self._sms_received(event)
        else:
            return False
        return True

    # ------------------------------------------------------------ notifications
    def _build_notifications_page(self) -> None:
        px = self.theme.px
        page, actions = self._page(
            "notifications", "Notifikationer", "Det, der dukker op på telefonen – her på PC'en."
        )
        Button(actions, self.theme, "Ryd alle", self._notif_clear_all, kind="ghost").pack(
            side="left"
        )
        self.notif_scroll = ScrollFrame(page, self.theme)
        self.notif_scroll.pack(fill="both", expand=True, padx=(px(36), px(24)), pady=(0, px(16)))
        self.notif_empty = self._notice(
            self.notif_scroll.inner,
            "Ingen notifikationer endnu.\n"
            "Slå det til på telefonen: Indstillinger → Telefon på PC'en. "
            "Så dukker telefonens beskeder op her, og du kan svare på dem.",
        )
        self.notif_empty.pack(fill="x", pady=px(8))

    def _notif_find(self, peer_id: str, key: str) -> NotifEntry | None:
        for item in self.notif_entries:
            if item.peer_id == peer_id and item.key == key:
                return item
        return None

    def _notif_received(self, event: NotificationReceived) -> None:
        existing = self._notif_find(event.peer_id, event.key)
        if existing is not None:  # the phone updates a notification in place
            existing.title, existing.text = event.title, event.text
            existing.time = event.time or existing.time
            existing.can_reply, existing.can_dismiss = event.can_reply, event.can_dismiss
            self._notif_rebuild(existing)
            return
        item = NotifEntry(event)
        first = self.notif_entries[0].card if self.notif_entries else None
        self.notif_entries.insert(0, item)
        self._notif_build(item, before=first)
        while len(self.notif_entries) > MAX_NOTIFICATIONS:
            self._notif_destroy(self.notif_entries.pop())
        self._notif_sync_empty()
        if getattr(self, "active_page", "") != "notifications":
            self.notif_unread += 1
            self._set_nav_badge("notifications", self.notif_unread)
        if self.config_store.get_flag("show_phone_notifications", True):
            message = f"{item.app}: {item.title} – {item.text}".strip(" –:")
            self._notify(message if len(message) <= 140 else message[:137] + "…")

    def _notif_removed(self, event: NotificationRemoved) -> None:
        item = self._notif_find(event.peer_id, event.key)
        if item is not None:
            self._notif_remove(item)

    def _notif_remove(self, item: NotifEntry) -> None:
        if item in self.notif_entries:
            self.notif_entries.remove(item)
        self._notif_destroy(item)
        self._notif_sync_empty()

    def _notif_destroy(self, item: NotifEntry) -> None:
        if item.card is not None:
            item.card.destroy()
            item.card = None

    def _notif_clear_all(self) -> None:
        for item in self.notif_entries:
            self._notif_destroy(item)
        self.notif_entries.clear()
        self.notif_unread = 0
        self._set_nav_badge("notifications", 0)
        self._notif_sync_empty()

    def _notif_sync_empty(self) -> None:
        if self.notif_entries:
            self.notif_empty.pack_forget()
        elif not self.notif_empty.winfo_manager():
            self.notif_empty.pack(fill="x", pady=self.theme.px(8))

    def _notif_rebuild(self, item: NotifEntry) -> None:
        index = self.notif_entries.index(item)
        later = [e.card for e in self.notif_entries[index + 1 :] if e.card is not None]
        self._notif_destroy(item)
        self._notif_build(item, before=later[0] if later else None)

    def _notif_icon(self, parent: tk.Misc, item: NotifEntry) -> tk.Widget:
        c = self.theme.c
        size = self.theme.px(34)
        box = tk.Frame(parent, bg=c["card"], width=size, height=size)
        box.pack_propagate(False)
        self._notif_icon_in(box, item, size).pack(expand=True)
        return box

    def _notif_icon_in(self, parent: tk.Misc, item: NotifEntry, size: int) -> tk.Widget:
        c = self.theme.c
        if item.icon_png:
            try:
                photo = tk.PhotoImage(data=base64.b64encode(item.icon_png))
                factor = max(1, -(-photo.width() // size))
                if factor > 1:
                    photo = photo.subsample(factor)
                item.photo = photo
                return tk.Label(parent, image=photo, bg=c["card"])
            except tk.TclError:
                item.photo = None
        canvas = tk.Canvas(parent, width=size, height=size, bg=c["card"], highlightthickness=0)
        soft = c["accent_soft"]
        canvas.create_oval(1, 1, size - 1, size - 1, fill=soft, outline=soft)
        canvas.create_text(
            size / 2,
            size / 2,
            text=(item.app[:1] or "?").upper(),
            fill=c["accent"],
            font=self.theme.font(11, "bold"),
        )
        return canvas

    def _notif_build(self, item: NotifEntry, before: tk.Widget | None = None) -> None:
        c = self.theme.c
        px = self.theme.px
        card = Card(self.notif_scroll.inner, self.theme, padding=14, radius=12)
        if before is not None:
            card.pack(fill="x", pady=(0, px(10)), before=before)
        else:
            card.pack(fill="x", pady=(0, px(10)))
        item.card = card
        body = card.body
        self._notif_icon(body, item).pack(side="left", anchor="n")
        content = tk.Frame(body, bg=c["card"])
        content.pack(side="left", fill="x", expand=True, padx=(px(12), 0))
        top = tk.Frame(content, bg=c["card"])
        top.pack(fill="x")
        tk.Label(
            top,
            text=item.app,
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9, "bold"),
        ).pack(side="left")
        tk.Label(
            top,
            text=f"  ·  {item.peer_name}",
            bg=c["card"],
            fg=c["faint"],
            font=self.theme.font(9),
        ).pack(side="left")
        item.time_label = tk.Label(
            top, text=ago(item.time), bg=c["card"], fg=c["faint"], font=self.theme.font(9)
        )
        item.time_label.pack(side="right")
        if item.title:
            tk.Label(
                content,
                text=item.title,
                bg=c["card"],
                fg=c["text"],
                font=self.theme.font(10, "bold"),
                anchor="w",
                justify="left",
            ).pack(fill="x", pady=(px(2), 0))
        if item.text:
            text = tk.Label(
                content,
                text=item.text,
                bg=c["card"],
                fg=c["text"],
                font=self.theme.font(10),
                anchor="w",
                justify="left",
                wraplength=px(520),
            )
            text.pack(fill="x")
            self._autowrap(text, content)
        if item.can_reply or item.can_dismiss:
            buttons = tk.Frame(content, bg=c["card"])
            buttons.pack(fill="x", pady=(px(8), 0))
            if item.can_reply:
                Button(
                    buttons,
                    self.theme,
                    "Svar",
                    lambda i=item: self._notif_toggle_reply(i),
                    size="sm",
                    kind="soft",
                ).pack(side="left", padx=(0, px(6)))
            if item.can_dismiss:
                Button(
                    buttons,
                    self.theme,
                    "Afvis",
                    lambda i=item: self._notif_dismiss(i),
                    size="sm",
                    kind="ghost",
                ).pack(side="left")
        item.content = content

    def _notif_toggle_reply(self, item: NotifEntry) -> None:
        if item.reply_row is not None:
            item.reply_row.destroy()
            item.reply_row = None
            return
        c = self.theme.c
        px = self.theme.px
        assert item.content is not None
        row = tk.Frame(item.content, bg=c["card"])
        row.pack(fill="x", pady=(px(8), 0))
        item.reply_row = row
        variable = tk.StringVar()
        box = entry(row, self.theme, variable)
        box.pack(side="left", fill="x", expand=True, ipady=px(5))

        def send() -> None:
            self._notif_reply(item, variable.get())

        box.bind("<Return>", lambda _e: send())
        Button(row, self.theme, "Send", send, kind="primary", size="sm").pack(
            side="left", padx=(px(8), 0)
        )
        box.focus_set()

    def _notif_reply(self, item: NotifEntry, text: str) -> None:
        text = text.strip()
        peer = self.peers.get(item.peer_id)
        if not text:
            return
        if peer is None:
            self._show_error(RuntimeError("Telefonen er ikke tilgængelig lige nu."))
            return

        def done(ok: bool, value: Any) -> None:
            if not ok:
                self._show_error(value)
                return
            if item.reply_row is not None:
                item.reply_row.destroy()
                item.reply_row = None
            self.toast.show(f"Svar sendt til {item.peer_name}", "success")

        self._phone_call(self.client.notification_action(peer, item.key, "reply", text), done)

    def _notif_dismiss(self, item: NotifEntry) -> None:
        peer = self.peers.get(item.peer_id)
        if peer is None:
            self._show_error(RuntimeError("Telefonen er ikke tilgængelig lige nu."))
            return

        def done(ok: bool, value: Any) -> None:
            if ok:
                self._notif_remove(item)
            else:
                self._show_error(value)

        self._phone_call(self.client.notification_action(peer, item.key, "dismiss"), done)

    def _notif_refresh_times(self) -> None:
        for item in self.notif_entries:
            if item.time_label is not None:
                item.time_label.configure(text=ago(item.time))

    def _notif_tick(self) -> None:
        """Keep "5 min siden" fresh; runs every minute for the life of the app."""
        if getattr(self, "_closing", False):
            return
        if getattr(self, "active_page", "") == "notifications":
            self._notif_refresh_times()
        self.after(60000, self._notif_tick)

    # --------------------------------------------------------------------- SMS
    def _build_sms_page(self) -> None:
        c = self.theme.c
        px = self.theme.px
        page, actions = self._page("sms", "SMS", "Læs og skriv telefonens beskeder fra PC'en.")
        Button(actions, self.theme, "Opdatér", self._sms_refresh, kind="ghost").pack(side="left")
        Button(actions, self.theme, "Ny besked", self._sms_new).pack(side="left", padx=(px(8), 0))
        self.sms_picker = tk.Frame(page, bg=c["bg"])
        self.sms_picker.pack(fill="x", padx=px(36), pady=(0, px(10)))
        self.sms_notice = self._notice(page, "")
        columns = tk.Frame(page, bg=c["bg"])
        columns.pack(fill="both", expand=True, padx=(px(36), px(24)), pady=(0, px(16)))
        self.sms_columns = columns
        left = tk.Frame(columns, bg=c["bg"], width=px(290))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.sms_thread_scroll = ScrollFrame(left, self.theme)
        self.sms_thread_scroll.pack(fill="both", expand=True)
        right = tk.Frame(columns, bg=c["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(px(16), 0))
        self.sms_title = tk.Label(
            right,
            text="",
            bg=c["bg"],
            fg=c["text"],
            font=self.theme.font(11, "bold"),
            anchor="w",
        )
        self.sms_title.pack(fill="x", pady=(0, px(8)))
        self.sms_compose = tk.Frame(right, bg=c["bg"])
        self.sms_compose.pack(side="bottom", fill="x", pady=(px(10), 0))
        self.sms_box = tk.Text(
            self.sms_compose,
            height=2,
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
        self.sms_box.pack(side="left", fill="x", expand=True)
        self.sms_box.bind("<Return>", self._sms_enter)
        Button(self.sms_compose, self.theme, "Send", self._sms_send, kind="primary").pack(
            side="left", padx=(px(8), 0), anchor="s"
        )
        self.sms_msg_scroll = ScrollFrame(right, self.theme)
        self.sms_msg_scroll.pack(fill="both", expand=True)
        self.sms_placeholder = self._notice(
            self.sms_msg_scroll.inner, "Vælg en samtale til venstre – eller tryk Ny besked."
        )
        self.sms_placeholder.pack(fill="x", pady=px(8))
        self.sms_compose.pack_forget()

    def _sms_show_notice(self, text: str, tone: str = "muted") -> None:
        if text:
            self.sms_notice.configure(
                text=text, fg=self.theme.c["danger"] if tone == "danger" else self.theme.c["muted"]
            )
            self.sms_notice.pack(
                fill="x",
                padx=self.theme.px(36),
                pady=(0, self.theme.px(8)),
                before=self.sms_columns,
            )
        else:
            self.sms_notice.pack_forget()

    def _sms_peer(self) -> Peer | None:
        return self.peers.get(self.sms_peer_id or "")

    def _sms_open(self) -> None:
        capable = self._fill_picker(self.sms_picker, "sms", self.sms_peer_id, self._sms_pick)
        peer = self._pick_current(capable, self.sms_peer_id)
        if peer is None:
            self.sms_peer_id = None
            self._sms_render_threads()
            self._sms_show_notice(
                "Ingen forbundne enheder kan sende og modtage SMS endnu. "
                "Forbind en Android-telefon – og tjek at appen er opdateret."
            )
            return
        self._sms_pick(peer)

    def _sms_pick(self, peer: Peer) -> None:
        changed = peer.device_id != self.sms_peer_id
        self.sms_peer_id = peer.device_id
        if changed:
            self.sms_current = None
            self._sms_render_current()
        self._fill_picker(self.sms_picker, "sms", peer.device_id, self._sms_pick)
        self._sms_render_threads()
        self._sms_refresh()

    def _sms_refresh(self) -> None:
        peer = self._sms_peer()
        if peer is None:
            return
        peer_id = peer.device_id

        def done(ok: bool, value: Any) -> None:
            if peer_id != self.sms_peer_id:
                return
            if not ok:
                self._sms_show_notice(self._sms_error_text(value), "danger")
                return
            self._sms_show_notice("")
            self.sms_threads[peer_id] = list(value)
            if self.sms_pending_address:
                for thread in value:
                    if thread.get("address") == self.sms_pending_address:
                        self.sms_pending_address = ""
                        self._sms_select(thread)
                        break
            self._sms_render_threads()

        self._phone_call(self.client.sms_threads(peer), done)

    def _sms_error_text(self, error: BaseException) -> str:
        message = self._phone_error(error)
        lowered = message.lower()
        if "kan ikke nå" in lowered or "svarede ikke" in lowered or "connect" in lowered:
            return f"Telefonen er offline lige nu. {message}"
        return message

    def _sms_render_threads(self) -> None:
        c = self.theme.c
        px = self.theme.px
        inner = self.sms_thread_scroll.inner
        for child in inner.winfo_children():
            child.destroy()
        threads = self.sms_threads.get(self.sms_peer_id or "", [])
        if not threads:
            self._notice(inner, "Ingen samtaler at vise.").pack(fill="x", pady=px(6))
            return
        current = (self.sms_current or {}).get("thread_id")
        for thread in threads:
            selected = thread.get("thread_id") == current
            bg = c["accent_soft"] if selected else c["card"]
            row = tk.Frame(inner, bg=bg, cursor="hand2", padx=px(12), pady=px(9))
            row.pack(fill="x", pady=(0, px(6)))
            top = tk.Frame(row, bg=bg)
            top.pack(fill="x")
            unread = bool(thread.get("unread"))
            tk.Label(
                top,
                text=thread.get("name") or thread.get("address") or "Ukendt",
                bg=bg,
                fg=c["text"],
                font=self.theme.font(10, "bold" if unread else "normal"),
                anchor="w",
            ).pack(side="left", fill="x", expand=True)
            if unread:
                tk.Label(top, text="●", bg=bg, fg=c["accent"], font=self.theme.font(8)).pack(
                    side="right"
                )
            tk.Label(
                top,
                text=clock(int(thread.get("time") or 0)),
                bg=bg,
                fg=c["faint"],
                font=self.theme.font(8),
            ).pack(side="right", padx=(px(6), 0))
            snippet = tk.Label(
                row,
                text=str(thread.get("snippet") or "").replace("\n", " "),
                bg=bg,
                fg=c["muted"],
                font=self.theme.font(9),
                anchor="w",
                justify="left",
            )
            snippet.pack(fill="x")
            self._autowrap(snippet, row, px(24))
            self._bind_click(row, lambda t=thread: self._sms_select(t))

    def _bind_click(self, widget: tk.Misc, command: Callable[[], None]) -> None:
        widget.bind("<Button-1>", lambda _e: command())
        for child in widget.winfo_children():
            self._bind_click(child, command)

    def _sms_select(self, thread: dict[str, Any]) -> None:
        self.sms_current = {
            "thread_id": str(thread.get("thread_id") or ""),
            "address": str(thread.get("address") or ""),
            "name": str(thread.get("name") or ""),
        }
        thread["unread"] = False
        self._sms_render_threads()
        self._sms_render_current()
        peer = self._sms_peer()
        if peer is None or not self.sms_current["thread_id"]:
            return
        peer_id, thread_id = peer.device_id, self.sms_current["thread_id"]

        def done(ok: bool, value: Any) -> None:
            if not ok:
                if peer_id == self.sms_peer_id:
                    self._sms_show_notice(self._sms_error_text(value), "danger")
                return
            self.sms_messages[(peer_id, thread_id)] = list(value)
            shown = (self.sms_current or {}).get("thread_id")
            if peer_id == self.sms_peer_id and shown == thread_id:
                self._sms_show_notice("")
                self._sms_render_messages()

        self._phone_call(self.client.sms_messages(peer, thread_id), done)

    def _sms_render_current(self) -> None:
        current = self.sms_current
        if current is None:
            self.sms_title.configure(text="")
            self.sms_compose.pack_forget()
            for child in self.sms_msg_scroll.inner.winfo_children():
                child.destroy()
            self.sms_placeholder = self._notice(
                self.sms_msg_scroll.inner, "Vælg en samtale til venstre – eller tryk Ny besked."
            )
            self.sms_placeholder.pack(fill="x", pady=self.theme.px(8))
            return
        label = current.get("name") or current.get("address") or ""
        if current.get("name") and current.get("address"):
            label = f"{current['name']}  ·  {current['address']}"
        self.sms_title.configure(text=label)
        self.sms_compose.pack(side="bottom", fill="x", pady=(self.theme.px(10), 0))
        self._sms_render_messages()

    def _sms_render_messages(self) -> None:
        c = self.theme.c
        px = self.theme.px
        inner = self.sms_msg_scroll.inner
        for child in inner.winfo_children():
            child.destroy()
        current = self.sms_current
        if current is None:
            return
        messages = self.sms_messages.get((self.sms_peer_id or "", current["thread_id"]), [])
        if not messages:
            self._notice(inner, "Ingen beskeder endnu.").pack(fill="x", pady=px(6))
        body_font = self.theme.font(10)
        max_text = px(380)
        for message in messages:
            outgoing = bool(message.get("outgoing"))
            row = tk.Frame(inner, bg=c["bg"])
            row.pack(fill="x", pady=(0, px(6)))
            text = str(message.get("body") or "")
            longest = max((body_font.measure(line) for line in text.split("\n")), default=0)
            text_width = min(max_text, longest + px(4))
            fill = c["accent"] if outgoing else c["card"]
            card = Card(row, self.theme, padding=10, radius=14, fill=fill)
            card.configure(width=text_width + 2 * px(10))
            card.pack(side="right" if outgoing else "left")
            tk.Label(
                card.body,
                text=text,
                bg=fill,
                fg=c["accent_text"] if outgoing else c["text"],
                font=body_font,
                justify="left",
                anchor="w",
                wraplength=max_text,
            ).pack(anchor="w")
            tk.Label(
                card.body,
                text=clock(int(message.get("time") or 0)),
                bg=fill,
                fg=c["accent_text"] if outgoing else c["faint"],
                font=self.theme.font(8),
            ).pack(anchor="e")
        self.sms_msg_scroll.update_idletasks()
        self.sms_msg_scroll.canvas.yview_moveto(1.0)

    def _sms_enter(self, event: tk.Event) -> str | None:
        if event.state & 0x1:  # Shift+Enter keeps the newline
            return None
        self._sms_send()
        return "break"

    def _sms_send(self) -> None:
        peer = self._sms_peer()
        current = self.sms_current
        text = self.sms_box.get("1.0", "end").strip()
        if peer is None or current is None or not text or not current.get("address"):
            return
        peer_id, address, thread_id = peer.device_id, current["address"], current["thread_id"]

        def done(ok: bool, value: Any) -> None:
            if not ok:
                self._show_error(RuntimeError(self._sms_error_text(value)))
                return
            self.sms_box.delete("1.0", "end")
            message = {
                "address": address,
                "body": text,
                "time": int(time.time() * 1000),
                "outgoing": True,
            }
            self._sms_add_message(peer_id, thread_id, address, current.get("name", ""), message)
            if not thread_id:
                self.sms_pending_address = address
                self.after(1500, self._sms_refresh)

        self._phone_call(self.client.send_sms(peer, address, text), done)

    def _sms_new(self) -> None:
        if self._sms_peer() is None:
            self._sms_open()
            if self._sms_peer() is None:
                return
        c = self.theme.c
        px = self.theme.px
        modal = Modal(self, self.theme, "Ny besked")
        modal.heading("Ny besked", "Skriv telefonnummeret, du vil sende til.")
        variable = tk.StringVar()
        box = entry(modal.body, self.theme, variable)
        box.pack(fill="x", pady=(px(14), 0), ipady=px(6))

        def go() -> None:
            number = variable.get().strip()
            if not number:
                return
            modal.close()
            self._sms_start_new(number)

        box.bind("<Return>", lambda _e: go())
        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(16), 0))
        Button(buttons, self.theme, "Fortsæt", go, kind="primary").pack(side="right")
        Button(buttons, self.theme, "Annullér", modal.close, kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        modal.present()
        box.focus_set()

    def _sms_start_new(self, number: str) -> None:
        for thread in self.sms_threads.get(self.sms_peer_id or "", []):
            if thread.get("address") == number:
                self._sms_select(thread)
                return
        self.sms_current = {"thread_id": "", "address": number, "name": ""}
        self._sms_render_threads()
        self._sms_render_current()
        self.sms_box.focus_set()

    def _sms_add_message(
        self, peer_id: str, thread_id: str, address: str, name: str, message: dict[str, Any]
    ) -> None:
        """Put a message into the caches and refresh whatever is on screen."""
        if thread_id:
            self.sms_messages.setdefault((peer_id, thread_id), []).append(message)
        threads = self.sms_threads.setdefault(peer_id, [])
        thread = next(
            (t for t in threads if thread_id and t.get("thread_id") == thread_id), None
        ) or next((t for t in threads if t.get("address") == address), None)
        if thread is None and thread_id:
            thread = {"thread_id": thread_id, "address": address, "name": name}
            threads.insert(0, thread)
        if thread is not None:
            thread["snippet"] = message.get("body", "")
            thread["time"] = message.get("time", 0)
            threads.remove(thread)
            threads.insert(0, thread)
        if peer_id != self.sms_peer_id:
            return
        self._sms_render_threads()
        current = self.sms_current
        if current is not None and (
            (thread_id and current["thread_id"] == thread_id)
            or (not current["thread_id"] and current["address"] == address)
        ):
            if not thread_id:
                self.sms_messages.setdefault((peer_id, ""), []).append(message)
            self._sms_render_messages()

    def _sms_received(self, event: SmsReceived) -> None:
        message = {
            "address": event.address,
            "body": event.body,
            "time": event.time or int(time.time() * 1000),
            "outgoing": False,
        }
        self._sms_add_message(event.peer_id, event.thread_id, event.address, event.name, message)
        open_here = (
            getattr(self, "active_page", "") == "sms"
            and event.peer_id == self.sms_peer_id
            and (self.sms_current or {}).get("thread_id") == event.thread_id
        )
        for thread in self.sms_threads.get(event.peer_id, []):
            if thread.get("thread_id") == event.thread_id:
                thread["unread"] = not open_here
                if event.name and not thread.get("name"):
                    thread["name"] = event.name
        if event.peer_id == self.sms_peer_id:
            self._sms_render_threads()
        if not open_here and getattr(self, "active_page", "") != "sms":
            self.sms_unread += 1
            self._set_nav_badge("sms", self.sms_unread)
        self._notify(f"SMS fra {event.name or event.address}: {event.body[:80]}")

    # --------------------------------------------------------------- remote page
    def _build_remote_page(self) -> None:
        c = self.theme.c
        px = self.theme.px
        page, _actions = self._page(
            "remote", "Fjernbetjening", "Find telefonen, tag skærmbillede og styr lyden."
        )
        self.remote_picker = tk.Frame(page, bg=c["bg"])
        self.remote_picker.pack(fill="x", padx=px(36), pady=(0, px(10)))
        self.remote_scroll = ScrollFrame(page, self.theme)
        self.remote_scroll.pack(fill="both", expand=True, padx=(px(36), px(24)), pady=(0, px(16)))
        self.remote_speak_var = tk.StringVar()

    def open_remote(self, peer: Peer) -> None:
        self.remote_peer_id = peer.device_id
        self.show_page("remote")

    def _remote_open(self) -> None:
        # Every paired device is listed; controls a phone cannot do are disabled with a hint.
        capable = self._fill_picker(
            self.remote_picker, None, self.remote_peer_id, self._remote_pick
        )
        peer = self._pick_current(capable, self.remote_peer_id)
        self.remote_peer_id = peer.device_id if peer else None
        self._fill_picker(self.remote_picker, None, self.remote_peer_id, self._remote_pick)
        self._remote_render()

    def _remote_pick(self, peer: Peer) -> None:
        self.remote_peer_id = peer.device_id
        self._remote_open()

    def _remote_card(self, title: str, hint: str, allowed: bool) -> Card:
        c = self.theme.c
        px = self.theme.px
        card = Card(self.remote_scroll.inner, self.theme)
        card.pack(fill="x", pady=(0, px(12)))
        tk.Label(
            card.body,
            text=title,
            bg=c["card"],
            fg=c["text"],
            font=self.theme.font(10, "bold"),
            anchor="w",
        ).pack(fill="x")
        subtitle = hint if allowed else f"{UPDATE_HINT} for at kunne dette."
        tk.Label(
            card.body,
            text=subtitle,
            bg=c["card"],
            fg=c["muted"] if allowed else c["warning"],
            font=self.theme.font(9),
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(px(2), px(10)))
        return card

    def _remote_render(self) -> None:
        c = self.theme.c
        px = self.theme.px
        for child in self.remote_scroll.inner.winfo_children():
            child.destroy()
        peer = self.peers.get(self.remote_peer_id or "")
        if peer is None:
            self._notice(
                self.remote_scroll.inner,
                "Ingen forbundne enheder kan fjernstyres endnu. Forbind en Android-telefon – "
                "og tjek at appen er opdateret.",
            ).pack(fill="x", pady=px(8))
            return
        can_find = peer.supports("find-phone")
        can_shot = peer.supports("screenshot-request")
        can_remote = peer.supports("remote-control")

        find = self._remote_card(
            "Find telefon",
            "Telefonen ringer højt – også på lydløs – til du stopper den.",
            can_find,
        )
        row = tk.Frame(find.body, bg=c["card"])
        row.pack(fill="x")
        self.remote_find_btn = Button(
            row, self.theme, "Find telefon", self.remote_find, kind="primary"
        )
        self.remote_find_btn.pack(side="left")
        self.remote_stop_btn = Button(row, self.theme, "Stop ringning", self.remote_stop_ring)
        self.remote_stop_btn.pack(side="left", padx=(px(8), 0))

        shot = self._remote_card(
            "Skærmbillede",
            "Du godkender på telefonen, og billedet åbner her på PC'en.",
            can_shot,
        )
        self.remote_shot_btn = Button(
            shot.body, self.theme, "Tag skærmbillede", self.remote_screenshot
        )
        self.remote_shot_btn.pack(anchor="w")

        sound = self._remote_card("Lyd", "Medielydstyrke og oplæsning på telefonen.", can_remote)
        vol = tk.Frame(sound.body, bg=c["card"])
        vol.pack(fill="x")
        tk.Label(vol, text="Lydstyrke", bg=c["card"], fg=c["muted"], font=self.theme.font(9)).pack(
            side="left"
        )
        self.remote_scale = Slider(vol, self.theme, 50, width=260)
        self.remote_scale.pack(side="left", padx=(px(12), px(12)))
        self.remote_volume_btn = Button(vol, self.theme, "Sæt", self.remote_set_volume)
        self.remote_volume_btn.pack(side="left")
        tk.Label(
            sound.body,
            text="Skriv noget, telefonen skal sige højt",
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
        ).pack(fill="x", pady=(px(14), px(4)))
        speak = tk.Frame(sound.body, bg=c["card"])
        speak.pack(fill="x")
        self.remote_speak_entry = entry(speak, self.theme, self.remote_speak_var)
        self.remote_speak_entry.pack(side="left", fill="x", expand=True, ipady=px(6))
        self.remote_speak_entry.bind("<Return>", lambda _e: self.remote_speak())
        self.remote_speak_btn = Button(speak, self.theme, "Læs højt", self.remote_speak)
        self.remote_speak_btn.pack(side="left", padx=(px(8), 0))

        paper = self._remote_card(
            "Baggrund", "Vælg et billede, der bliver telefonens baggrund.", can_remote
        )
        self.remote_paper_btn = Button(
            paper.body, self.theme, "Sæt baggrundsbillede…", self.remote_wallpaper
        )
        self.remote_paper_btn.pack(anchor="w")

        for allowed, widgets in (
            (can_find, (self.remote_find_btn, self.remote_stop_btn)),
            (can_shot, (self.remote_shot_btn,)),
            (
                can_remote,
                (self.remote_volume_btn, self.remote_speak_btn, self.remote_paper_btn),
            ),
        ):
            for widget in widgets:
                widget.set_enabled(allowed)
        if not can_remote:
            self.remote_scale.set_enabled(False)
            c = self.theme.c
            self.remote_speak_entry.configure(
                state="disabled", disabledbackground=c["entry"], disabledforeground=c["faint"]
            )

    def _remote_peer(self) -> Peer | None:
        return self.peers.get(self.remote_peer_id or "")

    def _remote_run(
        self,
        coroutine_for: Callable[[Peer], Coroutine[Any, Any, Any]],
        success: Callable[[Any], None],
    ) -> None:
        peer = self._remote_peer()
        if peer is None:
            return

        def done(ok: bool, value: Any) -> None:
            if ok:
                success(value)
            else:
                self._show_error(value)

        self._phone_call(coroutine_for(peer), done)

    def remote_find(self) -> None:
        self._remote_run(
            lambda p: self.client.find_phone(p, True),
            lambda _v: self.toast.show("Telefonen ringer nu", "success"),
        )

    def remote_stop_ring(self) -> None:
        self._remote_run(
            lambda p: self.client.find_phone(p, False),
            lambda _v: self.toast.show("Ringningen er stoppet", "success"),
        )

    def remote_screenshot(self) -> None:
        peer = self._remote_peer()

        def ok(_value: Any) -> None:
            if peer is not None:
                self.pending_screenshot = (
                    peer.device_id,
                    time.monotonic() + SCREENSHOT_WAIT_SECONDS,
                )
            self.toast.show(
                "Godkend på telefonen – billedet åbner her, når det kommer", duration_ms=6000
            )

        self._remote_run(lambda p: self.client.request_screenshot(p), ok)

    def remote_set_volume(self) -> None:
        level = int(self.remote_scale.value)
        self._remote_run(
            lambda p: self.client.set_volume(p, level),
            lambda value: self.toast.show(f"Lydstyrken er sat til {value} %", "success"),
        )

    def remote_speak(self) -> None:
        text = self.remote_speak_var.get().strip()
        if not text:
            return
        self._remote_run(
            lambda p: self.client.speak(p, text),
            lambda _v: self.toast.show("Telefonen læser højt", "success"),
        )

    def remote_wallpaper(self) -> None:
        path = filedialog.askopenfilename(
            title="Vælg baggrundsbillede", filetypes=IMAGE_TYPES, parent=self
        )
        if not path:
            return
        self._remote_run(
            lambda p: self.client.set_wallpaper(p, Path(path)),
            lambda _v: self.toast.show("Baggrunden er sat på telefonen", "success"),
        )

    def _maybe_open_screenshot(self, event: Any) -> None:
        """Open the screenshot we asked for, as soon as it arrives from that phone."""
        pending = self.pending_screenshot
        if pending is None or not str(event.path.name).startswith("Skaermbillede-"):
            return
        peer_id, deadline = pending
        if event.peer_id != peer_id or time.monotonic() > deadline:
            return
        self.pending_screenshot = None
        self.open_path_safely(str(event.path))

    # ------------------------------------------------------------ settings pieces
    def _build_phone_settings(self, section: Callable[[str], Card]) -> None:
        phone = section("Telefonen")
        self._toggle_row(
            phone.body,
            "Vis telefonens notifikationer som Windows-beskeder",
            "Nye notifikationer fra telefonen dukker også op som en besked på PC'en.",
            self.config_store.get_flag("show_phone_notifications", True),
            lambda value: self.config_store.set_flag("show_phone_notifications", value),
        )
        cloud = section("Sky (valgfri)")
        self.drive_body = cloud.body
        self._drive_render()

    def _drive_render(self) -> None:
        c = self.theme.c
        px = self.theme.px
        body = self.drive_body
        for child in body.winfo_children():
            child.destroy()
        status = self.gdrive.status()

        def line(text: str, strong: bool = False, muted: bool = False) -> tk.Label:
            label = tk.Label(
                body,
                text=text,
                bg=c["card"],
                fg=c["muted"] if muted else c["text"],
                font=self.theme.font(10 if strong else 9, "bold" if strong else "normal"),
                anchor="w",
                justify="left",
                wraplength=px(520),
            )
            label.pack(fill="x", pady=(0, px(2)))
            return label

        line("Google Drive", strong=True)
        if self.drive_busy:
            line(self.drive_busy, muted=True)
            return
        if status["connected"]:
            line(f"Forbundet som {status['email'] or 'din Google-konto'}", muted=True)
            line(
                "h4xtor share kan kun se de filer, den selv har lavet – aldrig resten af dit "
                "Drive.",
                muted=True,
            )
            row = tk.Frame(body, bg=c["card"])
            row.pack(fill="x", pady=(px(10), 0))
            Button(row, self.theme, "Test forbindelse", self._drive_test).pack(side="left")
            Button(row, self.theme, "Afbryd", self._drive_disconnect_ask, kind="ghost").pack(
                side="left", padx=(px(8), 0)
            )
            return
        line(
            "Ikke forbundet. Slået fra, indtil du selv forbinder – der kontaktes ikke Google før.",
            muted=True,
        )
        row = tk.Frame(body, bg=c["card"])
        row.pack(fill="x", pady=(px(10), 0))
        Button(row, self.theme, "Forbind Google Drive", self._drive_connect).pack(side="left")

    def _drive_connect(self) -> None:
        if not self.gdrive.status()["configured"]:
            self._drive_setup_help()
            return
        self.drive_busy = "Venter på Google… Fuldfør login i browseren."
        self._drive_render()

        def done(ok: bool, value: Any) -> None:
            self.drive_busy = ""
            self._drive_render()
            if ok:
                self.toast.show(f"Forbundet som {value}", "success")
            else:
                self._show_error(self._drive_error(value))

        self._phone_call(self.gdrive.connect(webbrowser.open), done)

    def _drive_error(self, error: BaseException) -> BaseException:
        return error if isinstance(error, GoogleDriveError) else RuntimeError(str(error))

    def _drive_setup_help(self) -> None:
        c = self.theme.c
        px = self.theme.px
        modal = Modal(self, self.theme, "Google Drive", width=560)
        modal.heading(
            "Google Drive skal sættes op først",
            "Det er en engangsopsætning, og den tager nogle minutter.",
        )
        tk.Label(
            modal.body,
            text=SETUP_HELP,
            bg=c["bg"],
            fg=c["text"],
            font=self.theme.font(10),
            justify="left",
            anchor="w",
            wraplength=px(500),
        ).pack(fill="x", pady=(px(14), 0))
        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(16), 0))
        Button(buttons, self.theme, "Luk", modal.close, kind="primary").pack(side="right")
        modal.present()

    def _drive_test(self) -> None:
        def done(ok: bool, value: Any) -> None:
            if not ok:
                self._show_error(self._drive_error(value))
                return
            if value:
                names = ", ".join(str(name) for name in value[:3])
                text = f"Forbindelsen virker. Fundet {len(value)}: {names}"
                self.toast.show(text, "success", duration_ms=6000)
            else:
                self._drive_note(
                    "Forbindelsen virker",
                    "Der er ingen filer endnu. Det er helt normalt: h4xtor share kan kun se "
                    "sine egne filer, ikke resten af dit Drive.",
                )

        self._phone_call(self.gdrive.list_root(), done)

    def _drive_note(self, heading: str, text: str) -> None:
        c = self.theme.c
        px = self.theme.px
        modal = Modal(self, self.theme, "Google Drive")
        modal.heading(heading, text)
        buttons = tk.Frame(modal.body, bg=c["bg"])
        buttons.pack(fill="x", pady=(px(16), 0))
        Button(buttons, self.theme, "Luk", modal.close, kind="primary").pack(side="right")
        modal.present()

    def _drive_disconnect_ask(self) -> None:
        self._confirm_danger(
            "Google Drive",
            "Afbryd Google Drive?",
            "Forbindelsen fjernes fra denne PC. Dine filer på Drive bliver ikke slettet.",
            "Afbryd",
            self._drive_disconnect,
        )

    def _drive_disconnect(self) -> None:
        def done(ok: bool, value: Any) -> None:
            self._drive_render()
            if ok:
                self.toast.show("Google Drive er afbrudt")
            else:
                self._show_error(self._drive_error(value))

        self._phone_call(self.gdrive.disconnect(), done)
