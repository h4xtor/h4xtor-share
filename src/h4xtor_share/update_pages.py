"""Update dialogs of the desktop app: "Ny version", "Opdateringslog" and the welcome note.

Mixed into ``H4xtorShareApp``. Network work runs on the asyncio runtime and comes
back on the Tk thread as an ``update_result`` / ``update_progress`` event.
"""

from __future__ import annotations

import tempfile
import tkinter as tk
import webbrowser
from pathlib import Path
from typing import Any

from h4xtor_share import __version__
from h4xtor_share.ui_kit import Button, Modal
from h4xtor_share.updater import (
    NO_CHANGELOG,
    SECTIONS,
    ChangelogEntry,
    Release,
    UpdateError,
    can_self_install,
    entries_between,
    is_newer,
    mark_started,
    start_helper,
)

AUTO_TICK_MS = 3600 * 1000  # re-evaluate hourly; the updater itself allows one check a day


class UpdateMixin:
    # Provided by H4xtorShareApp.
    theme: Any
    toast: Any
    runtime: Any
    event_queue: Any
    config_store: Any
    transfers: dict[str, Any]
    tray: Any
    updater: Any

    def _start_updates(self) -> None:
        self._update_modal: Modal | None = None
        self._update_status: tk.Label | None = None
        self._update_buttons: tk.Frame | None = None
        note = mark_started(self.config_store.path.parent)
        last = str(self.config_store.data.get("last_run_version") or "")
        if last != __version__:
            self.config_store.data["last_run_version"] = __version__
            self.config_store.save()
        if note:
            title = "Opdateringen blev ikke gennemført"
            self.after(1200, lambda: self._update_message(title, note))
        elif last and is_newer(__version__, last):
            self.after(1200, lambda: self._show_welcome(last))
        self.after(5000, self._auto_update_tick)

    # -- checking ------------------------------------------------------------------
    def _auto_update_tick(self) -> None:
        if self.updater.due():
            self._run_update_check(manual=False)
        self.after(AUTO_TICK_MS, self._auto_update_tick)

    def check_for_updates_now(self) -> None:
        self.toast.show("Søger efter en ny version…")
        self._run_update_check(manual=True)

    def _run_update_check(self, manual: bool) -> None:
        async def run() -> tuple[str, Any, bool]:
            try:
                found = await self.updater.check()
            except Exception as error:  # noqa: BLE001 - offline stays quiet unless asked
                return "offline", error, manual
            return ("found" if found else "none"), found, manual

        self.runtime.submit(run(), "update_result")

    def _update_event(self, tag: str, value: Any) -> None:
        if tag == "update_progress":
            done, total = value
            if self._update_status is not None and total:
                mb = 1024 * 1024
                self._update_status.configure(
                    text=f"Henter … {done / mb:.1f} af {total / mb:.1f} MB "
                    f"({done * 100 // total} %)"
                )
            return
        kind, payload, manual = value
        if kind == "found":
            release, entries = payload
            if manual or self.updater.should_prompt(release.version):
                self._show_update_dialog(release, entries)
        elif kind == "none" and manual:
            self.toast.show(f"Du har den nyeste version ({__version__}) ✓", "success")
        elif kind == "offline" and manual:
            self.toast.show("Kunne ikke nå GitHub – tjek din internetforbindelse.", "warning")
        elif kind == "ready":
            self._install_update(payload)
        elif kind == "failed":
            self._update_failed(payload)

    # -- dialogs ---------------------------------------------------------------------
    def _changelog_box(
        self, parent: tk.Misc, entries: list[ChangelogEntry], limit: int = 3
    ) -> tk.Text:
        c = self.theme.c
        px = self.theme.px
        frame = tk.Frame(
            parent, bg=c["card"], highlightthickness=1, highlightbackground=c["border"]
        )
        frame.pack(fill="both", expand=True, pady=(px(14), 0))
        text = tk.Text(
            frame,
            height=12,
            wrap="word",
            bg=c["card"],
            fg=c["text"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=px(14),
            pady=px(12),
            font=self.theme.font(10),
            cursor="arrow",
        )
        bar = tk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("version", font=self.theme.font(11, "bold"))
        text.tag_configure("section", font=self.theme.font(10, "bold"), foreground=c["accent"])
        text.tag_configure("muted", foreground=c["muted"])

        def fill(count: int) -> None:
            text.configure(state="normal")
            text.delete("1.0", "end")
            if not entries:
                text.insert("end", NO_CHANGELOG, "muted")
            for index, entry in enumerate(entries[:count]):
                if index:
                    text.insert("end", "\n\n")
                text.insert("end", f"Version {entry.version}", "version")
                text.insert("end", f"   {entry.date}", "muted")
                for name in SECTIONS:
                    for number, item in enumerate(entry.sections.get(name) or []):
                        if number == 0:
                            text.insert("end", f"\n\n{name}", "section")
                        text.insert("end", f"\n•  {item}")
            text.configure(state="disabled")

        fill(limit)
        if len(entries) > limit:
            more: Button

            def show_all() -> None:
                fill(len(entries))
                more.pack_forget()

            more = Button(
                parent, self.theme, f"Vis alt ({len(entries)} versioner)", show_all,
                kind="ghost", size="sm",
            )
            more.pack(anchor="w", pady=(px(6), 0))
        return text

    def _note(self, parent: tk.Misc, text: str, tone: str = "muted") -> tk.Label:
        c = self.theme.c
        label = tk.Label(
            parent,
            text=text,
            bg=c["bg"],
            fg=c[tone],
            font=self.theme.font(9),
            anchor="w",
            justify="left",
            wraplength=self.theme.px(470),
        )
        label.pack(fill="x", pady=(self.theme.px(10), 0))
        return label

    def _show_update_dialog(self, release: Release, entries: list[ChangelogEntry]) -> None:
        if self._update_modal is not None:
            self._update_modal.close()
        px = self.theme.px
        modal = Modal(self, self.theme, "Ny version", width=540)
        modal.heading(
            f"Version {release.version} er klar",
            f"Du har version {__version__}. Her er det nye:",
        )
        self._changelog_box(modal.body, entries)
        if any(state.status == "active" for state in self.transfers.values()):
            self._note(
                modal.body,
                "En overførsel er i gang. Den bliver afbrudt, hvis du opdaterer nu.",
                "warning",
            )
        if not can_self_install():
            self._note(
                modal.body,
                "På denne computer åbner “Opdatér nu” download-siden på GitHub.",
            )
        self._update_status = self._note(modal.body, "")
        buttons = tk.Frame(modal.body, bg=self.theme.c["bg"])
        buttons.pack(fill="x", pady=(px(16), 0))
        version = release.version

        def update_now() -> None:
            if not can_self_install():
                webbrowser.open(release.page_url)
                modal.close()
                return
            for child in buttons.winfo_children():
                child.destroy()
            if self._update_status is not None:
                self._update_status.configure(text="Henter opdateringen …")
            self._download_update(release)

        def later() -> None:
            self.updater.later(version)
            modal.close()

        def skip() -> None:
            self.updater.skip(version)
            modal.close()
            self.toast.show(f"Version {version} springes over")

        Button(buttons, self.theme, "Opdatér nu", update_now, kind="primary").pack(side="right")
        Button(buttons, self.theme, "Senere", later, kind="ghost").pack(
            side="right", padx=(0, px(8))
        )
        Button(buttons, self.theme, "Spring denne version over", skip, kind="ghost").pack(
            side="left"
        )
        self._update_buttons = buttons

        def closed() -> None:
            self._update_modal = None
            self._update_status = None

        modal.on_close = closed
        self._update_modal = modal
        modal.present()

    def _download_update(self, release: Release) -> None:
        folder = Path(tempfile.gettempdir()) / "h4xtor-update"

        def progress(done: int, total: int) -> None:
            self.event_queue.put(("update_progress", (done, total)))

        async def run() -> tuple[str, Any, bool]:
            try:
                return "ready", await self.updater.download(release, folder, progress), True
            except Exception as error:  # noqa: BLE001 - shown to the user
                return "failed", error, True

        self.runtime.submit(run(), "update_result")

    def _install_update(self, path: Path) -> None:
        if self._update_status is not None:
            self._update_status.configure(text="Tjeksum OK ✓ – genstarter h4xtor share …")
        self.update_idletasks()
        try:
            start_helper(path, self.config_store.path.parent)
        except Exception as error:  # noqa: BLE001
            self._update_failed(error)
            return
        self.after(300, self.close)

    def _update_failed(self, error: Exception) -> None:
        message = (
            str(error)
            if isinstance(error, UpdateError)
            else "Kunne ikke hente opdateringen – tjek din internetforbindelse og prøv igen."
        )
        if self._update_status is not None:
            self._update_status.configure(text=message, fg=self.theme.c["danger"])
        if self._update_buttons is not None and self._update_modal is not None:
            Button(
                self._update_buttons, self.theme, "Luk", self._update_modal.close, kind="ghost"
            ).pack(side="right")
        else:
            self.toast.show(message, "danger", duration_ms=6000)

    def show_changelog(self) -> None:
        modal = Modal(self, self.theme, "Opdateringslog", width=540)
        modal.heading("Opdateringslog", f"Du kører version {__version__}.")
        self._changelog_box(modal.body, self.updater.changelog(), limit=5)
        Button(modal.body, self.theme, "Luk", modal.close, kind="ghost").pack(
            anchor="e", pady=(self.theme.px(16), 0)
        )
        modal.present()

    def _show_welcome(self, previous: str) -> None:
        title = f"Velkommen til version {__version__}"
        if self.state() == "withdrawn":  # started quietly in the tray
            if self.tray is not None:
                self.tray.notify(title)
            return
        modal = Modal(self, self.theme, title, width=540)
        modal.heading(title, f"Her er det nye siden version {previous}:")
        self._changelog_box(
            modal.body, entries_between(self.updater.changelog(), previous, __version__)
        )
        Button(modal.body, self.theme, "Fint", modal.close, kind="primary").pack(
            anchor="e", pady=(self.theme.px(16), 0)
        )
        modal.present()

    def _update_message(self, title: str, text: str) -> None:
        modal = Modal(self, self.theme, title)
        modal.heading(title, text)
        Button(modal.body, self.theme, "OK", modal.close, kind="primary").pack(
            anchor="e", pady=(self.theme.px(16), 0)
        )
        modal.present()
