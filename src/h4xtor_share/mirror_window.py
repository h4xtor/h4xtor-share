"""The phone's screen, live, on the PC's "Styr telefon" page – steered with the mouse and keyboard.

The phone shares its screen only after the user taps "Start" on it, shows a notification all
the while, and taps arrive through its accessibility service (Android only: Apple lets no app
see or steer an iPhone).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import time
import tkinter as tk
from concurrent.futures import Future
from typing import Any

from h4xtor_share.models import Peer
from h4xtor_share.ui_kit import Avatar, Button, Card, ScrollFrame, Toggle, glass_image, round_rect

TAP_PIXELS = 8  # a press that moves less than this is a tap, not a swipe


def gesture(start: tuple[float, float], end: tuple[float, float], seconds: float,
            size: tuple[int, int]) -> dict[str, Any]:
    """A mouse press and release on the picture as a phone gesture, in screen fractions."""
    width, height = size
    x1, y1 = start[0] / width, start[1] / height
    x2, y2 = end[0] / width, end[1] / height

    def inside(value: float) -> float:
        return min(1.0, max(0.0, value))

    if abs(end[0] - start[0]) < TAP_PIXELS and abs(end[1] - start[1]) < TAP_PIXELS:
        return {"type": "tap", "x": inside(x1), "y": inside(y1)}
    return {"type": "swipe", "x": inside(x1), "y": inside(y1), "x2": inside(x2),
            "y2": inside(y2), "ms": int(min(3000, max(80, seconds * 1000)))}


def wheel(delta: int) -> dict[str, Any]:
    """The mouse wheel as a swipe: rolling down scrolls the page down (the finger goes up)."""
    up = delta > 0
    return {"type": "swipe", "x": 0.5, "y": 0.4 if up else 0.65, "x2": 0.5,
            "y2": 0.65 if up else 0.4, "ms": 180}


class MirrorView(tk.Frame):
    """The "Styr telefon" page body: the phone in a rounded frame on the left, its controls on
    the right (who, Start/Stop, the phone's buttons, typing and AI control)."""

    BEZEL = 12

    def __init__(self, parent: tk.Misc, app: Any) -> None:
        self.app, self.theme = app, app.theme
        c, px = self.theme.c, self.theme.px
        super().__init__(parent, bg=c["bg"])
        self.peer: Peer | None = None
        self.running = False
        self.session = 0  # bumped on every start/stop, so a stopped frame loop goes quiet
        self.seq = 0
        self.size = (0, 0)  # the picture as shown
        self.control: bool | None = None  # can the phone's accessibility service tap?
        self._press: tuple[float, float, float] | None = None
        self._image: Any = None
        self._device_image: Any = None
        try:
            from PIL import Image, ImageTk  # noqa: F401  (Windows builds ship Pillow)

            self.format = "jpeg"
        except ImportError:
            self.format = "png"  # Tk reads PNG itself

        # ---- left: the phone in a rounded frame
        self.left = tk.Frame(self, bg=c["bg"])
        self.left.pack(side="left", fill="y", padx=(0, px(24)))
        self.device = tk.Canvas(self.left, bg=c["bg"], highlightthickness=0, bd=0)
        self.device.pack(anchor="n")
        self.canvas = tk.Canvas(self.device, bg="#000000", highlightthickness=0, bd=0,
                                cursor="hand2")
        self.device.create_window(px(self.BEZEL), px(self.BEZEL) + px(10), window=self.canvas,
                                  anchor="nw")
        self.left.bind("<Configure>", lambda _e: self.size == (0, 0) and self._placeholder())

        # ---- right: Play Store-style details
        scroll = ScrollFrame(self, self.theme)
        scroll.pack(side="left", fill="both", expand=True)
        right = scroll.inner
        head = tk.Frame(right, bg=c["bg"])
        head.pack(fill="x", pady=(px(4), px(16)))
        self.avatar_host = tk.Frame(head, bg=c["bg"])
        self.avatar_host.pack(side="left", anchor="n")
        who = tk.Frame(head, bg=c["bg"])
        who.pack(side="left", fill="x", expand=True, padx=(px(16), 0))
        self.name = tk.Label(who, text="Ingen telefon", bg=c["bg"], fg=c["text"], anchor="w",
                             font=self.theme.title_font(20))
        self.name.pack(fill="x")
        self.meta = tk.Label(who, text="", bg=c["bg"], fg=c["accent"], anchor="w",
                             font=self.theme.font(10, "bold"))
        self.meta.pack(fill="x")
        self.status = tk.Label(who, text="", bg=c["bg"], fg=c["muted"], anchor="w",
                               justify="left", font=self.theme.font(9))
        self.status.pack(fill="x", pady=(px(2), 0))
        who.bind("<Configure>", lambda e: self.status.configure(wraplength=max(160, e.width)))
        self.start_button = Button(right, self.theme, "Start", self.toggle, kind="primary",
                                   size="xl", icon="▶", width=320)
        self.start_button.pack(anchor="w", pady=(0, px(16)))

        self.warning = Card(right, self.theme, fill=c["warning_soft"], outline=c["warning"])
        tk.Label(self.warning.body, text="⚠  PC'en kan ikke trykke på telefonen endnu",
                 bg=c["warning_soft"], fg=c["warning"], anchor="w",
                 font=self.theme.font(10, "bold")).pack(fill="x")
        hint = tk.Label(self.warning.body, bg=c["warning_soft"], fg=c["text"], anchor="w",
                        justify="left", font=self.theme.font(9),
                        text="Tryk på beskeden “Tillad styring fra PC'en” på telefonen, og slå "
                             "h4xtor share til under Hjælpefunktioner. Så virker klik med det "
                             "samme – billedet vises allerede.")
        hint.pack(fill="x", pady=(px(4), 0))
        self.warning.body.bind("<Configure>",
                               lambda e: hint.configure(wraplength=max(160, e.width)), add="+")

        self.keys = self._card(right, "Telefonens knapper", "Højreklik på skærmen er også Tilbage.")
        row = tk.Frame(self.keys.body, bg=c["card"])
        row.pack(fill="x")
        self.key_buttons = []
        for label, kind in (("◀  Tilbage", "back"), ("●  Hjem", "home"), ("▢  Apps", "recents")):
            button = Button(row, self.theme, label, lambda k=kind: self.send({"type": k}))
            button.pack(side="left", padx=(0, px(8)))
            self.key_buttons.append(button)

        typing = self._card(right, "Skriv på telefonen",
                            "Tryk først i et tekstfelt på telefonen, og skriv så her.")
        row = tk.Frame(typing.body, bg=c["card"])
        row.pack(fill="x")
        self.text = tk.Entry(row, bg=c["entry"], fg=c["text"], insertbackground=c["accent"],
                             relief="flat", bd=px(6), highlightthickness=1,
                             highlightbackground=c["border_strong"], highlightcolor=c["accent"],
                             font=self.theme.font(10))
        self.text.pack(side="left", fill="x", expand=True, ipady=px(1))
        self.text.bind("<Return>", lambda _e: self.type_text())
        self.type_button = Button(row, self.theme, "Skriv", self.type_text, kind="primary")
        self.type_button.pack(side="left", padx=(px(8), 0))

        ai = self._card(right, "AI-styring",
                        "En AI som Claude kan se skærmen og trykke og skrive for dig. Tryk "
                        "“Kopiér AI-opsætning” og indsæt den i AI'ens MCP-indstillinger.")
        row = tk.Frame(ai.body, bg=c["card"])
        row.pack(fill="x")
        tk.Label(row, text="Lad en AI styre telefonen", bg=c["card"], fg=c["text"],
                 font=self.theme.font(10)).pack(side="left")
        self.ai_toggle = Toggle(row, self.theme, app.config_store.get_flag("ai_control", False),
                                lambda value: app._set_ai_control(value))
        self.ai_toggle.pack(side="right")
        Button(ai.body, self.theme, "Kopiér AI-opsætning", lambda: app._copy_ai_setup(),
               kind="secondary", size="sm").pack(anchor="w", pady=(px(10), 0))

        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.canvas.bind("<Button-3>", lambda _e: self.send({"type": "back"}))
        self.canvas.bind("<MouseWheel>", lambda e: self.send(wheel(e.delta)))
        self.canvas.bind("<Button-4>", lambda _e: self.send(wheel(120)))
        self.canvas.bind("<Button-5>", lambda _e: self.send(wheel(-120)))
        self.show(None)

    def _card(self, parent: tk.Misc, title: str, hint: str) -> Card:
        c, px = self.theme.c, self.theme.px
        card = Card(parent, self.theme)
        card.pack(fill="x", pady=(0, px(12)))
        tk.Label(card.body, text=title, bg=c["card"], fg=c["text"], anchor="w",
                 font=self.theme.font(10, "bold")).pack(fill="x")
        label = tk.Label(card.body, text=hint, bg=c["card"], fg=c["muted"], anchor="w",
                         justify="left", font=self.theme.font(9))
        label.pack(fill="x", pady=(px(2), px(10)))
        card.body.bind("<Configure>", lambda e: label.configure(wraplength=max(160, e.width)),
                       add="+")
        return card

    # ------------------------------------------------------------ the phone
    def _tall(self) -> int:
        """How tall the screen may be: the page's height minus the frame around it."""
        height = self.left.winfo_height()
        if height < 100:
            height = int(self.winfo_screenheight() * 0.6)
        return max(200, height - 2 * self.theme.px(self.BEZEL) - self.theme.px(24))

    def _frame_device(self, width: int, height: int) -> None:
        c, px = self.theme.c, self.theme.px
        bezel, top = px(self.BEZEL), px(10)
        self.canvas.configure(width=width, height=height)
        total_w, total_h = width + 2 * bezel, height + 2 * bezel + 2 * top
        self.device.configure(width=total_w, height=total_h)
        self._device_image = glass_image(self.device, total_w, total_h, px(30), c["chrome"],
                                         c["bg"], c["border_strong"], 1.5)
        self.device.delete("frame")
        self.device.create_image(0, 0, image=self._device_image, anchor="nw", tags=("frame",))
        round_rect(self.device, total_w / 2 - px(22), bezel - px(2), total_w / 2 + px(22),
                   bezel + px(4), px(3), fill=c["border_strong"], outline="", tags=("frame",))
        self.device.tag_lower("frame")

    def _placeholder(self, text: str = "") -> None:
        c = self.theme.c
        self.size = (0, 0)
        self._image = None
        tall = self._tall()
        width = tall * 9 // 19
        self._frame_device(width, tall)
        self.canvas.delete("all")
        self.canvas.create_text(width / 2, tall / 2, width=width - 40, justify="center",
                                fill=c["faint"], font=self.theme.font(10),
                                text=text or self._waiting_text())

    def _waiting_text(self) -> str:
        if self.peer is None:
            return "Ingen telefon valgt"
        if self.running:
            return "Tryk “Start nu” på telefonen …"
        return "Tryk Start for at se telefonens skærm"

    def show(self, peer: Peer | None, meta: str = "", allowed: bool = True,
             online: bool = False) -> None:
        """Show this phone (stops a running mirror of another one)."""
        if self.peer is not None and (peer is None or peer.device_id != self.peer.device_id):
            self.stop()
        self.peer = peer
        for child in self.avatar_host.winfo_children():
            child.destroy()
        Avatar(self.avatar_host, self.theme, peer.platform if peer else "", size=64).pack()
        self.name.configure(text=peer.name if peer else "Ingen telefon")
        self.meta.configure(text=meta, fg=self.theme.c["success" if online else "muted"])
        self.ai_toggle.set(self.app.config_store.get_flag("ai_control", False))
        self.start_button.set_enabled(peer is not None and allowed)
        if peer is None:
            self._say("Forbind en Android-telefon med h4xtor share for at se og styre den.")
        elif not allowed:
            self._say("Slået fra på PC'en: Indstillinger → Ekstra funktioner → "
                      "“Telefonens skærm på PC'en”.")
        elif not self.running:
            self._say("Telefonen spørger først, og en besked viser hele tiden, at PC'en ser med.")
        self._refresh()

    def _refresh(self) -> None:
        self.start_button.kind = "danger" if self.running else "primary"
        self.start_button._icon = "■" if self.running else "▶"
        self.start_button.set_text("Stop spejling" if self.running else "Start spejling")
        for button in (*self.key_buttons, self.type_button):
            button.set_enabled(self.running)
        if self.control is False and self.running:
            if not self.warning.winfo_manager():
                self.warning.pack(fill="x", pady=(0, self.theme.px(12)), before=self.keys)
        elif self.warning.winfo_manager():
            self.warning.pack_forget()
        if self.size == (0, 0):
            self._placeholder()

    # ------------------------------------------------------------ plumbing
    def _run(self, coroutine: Any, done: Any) -> None:
        """Run on the app's network loop; hand the outcome back to Tk (polled, thread-safe)."""
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, self.app.runtime.loop)
        session = self.session

        def check() -> None:
            if session != self.session:
                future.cancel()
                return
            if not future.done():
                self.after(25, check)
                return
            try:
                done(future.result(), None)
            except Exception as error:  # noqa: BLE001 – shown to the user
                done(None, error)

        self.after(25, check)

    def _say(self, text: str) -> None:
        with contextlib.suppress(tk.TclError):
            self.status.configure(text=text)

    def toggle(self) -> None:
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self.peer is None or self.running:
            return
        self.session += 1
        self.running, self.seq, self.control = True, 0, None
        self._say("Tryk “Start nu” på telefonen for at dele skærmen …")
        self._refresh()
        self._run(self.app.client.mirror_start(self.peer, self.format), self._started)

    def _control(self, reply: dict[str, Any] | None) -> None:
        if reply and "control" in reply and bool(reply["control"]) != self.control:
            self.control = bool(reply["control"])
            self._refresh()

    def _started(self, result: Any, error: BaseException | None) -> None:
        if error is not None:
            self.running = False
            self._refresh()
            self._say(f"Kunne ikke starte: {error}")
            return
        self._control(result if isinstance(result, dict) else None)
        self._next()

    def _next(self) -> None:
        assert self.peer is not None
        self._run(self.app.client.mirror_frame(self.peer, self.seq), self._frame)

    def _frame(self, frame: dict[str, Any] | None, error: BaseException | None) -> None:
        if error is not None:
            self._say(f"Forbindelsen drillede: {error}")
            self.after(1000, lambda session=self.session: session == self.session and self._next())
            return
        assert frame is not None
        if not frame.get("active"):
            if frame.get("waiting"):
                self._say("Tryk “Start nu” på telefonen for at dele skærmen …")
                self.after(600, lambda s=self.session: s == self.session and self._next())
            else:
                self.running = False
                self.session += 1
                self.size = (0, 0)
                self._refresh()
                self._say("Skærmdelingen er stoppet på telefonen. Tryk Start for at se den igen.")
            return
        self._control(frame)
        if frame.get("image") and int(frame.get("seq", 0)) != self.seq:
            self.seq = int(frame["seq"])
            self._show(base64.b64decode(frame["image"]), frame.get("format", "png"))
            self._say("Klik for at trykke · træk for at swipe · hjulet ruller · "
                      "højreklik er Tilbage")
        self._next()

    def _show(self, data: bytes, kind: str) -> None:
        tall = self._tall()
        if kind == "jpeg":
            import io

            from PIL import Image, ImageTk

            picture = Image.open(io.BytesIO(data))
            scale = min(1.0, tall / picture.height)
            if scale < 1:
                picture = picture.resize((int(picture.width * scale), int(picture.height * scale)))
            self._image = ImageTk.PhotoImage(picture, master=self)
        else:
            image = tk.PhotoImage(master=self, data=base64.b64encode(data).decode("ascii"))
            shrink = max(1, -(-image.height() // tall))  # whole steps only: Tk has no resize
            self._image = image.subsample(shrink) if shrink > 1 else image
        size = (self._image.width(), self._image.height())
        if size != self.size:
            self.size = size
            self._frame_device(*size)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._image, anchor="nw")

    # --------------------------------------------------------------- input
    def _down(self, event: tk.Event) -> None:
        self._press = (event.x, event.y, time.monotonic())

    def _up(self, event: tk.Event) -> None:
        if self._press is None or not self.size[0]:
            return
        x, y, at = self._press
        self._press = None
        self.send(gesture((x, y), (event.x, event.y), time.monotonic() - at, self.size))

    def send(self, action: dict[str, Any]) -> None:
        if not self.running or self.peer is None:
            return
        if self.control is False:  # the tap would vanish: say why instead of doing nothing
            self._say("Klikket nåede ikke frem: slå styring til på telefonen (se den gule boks).")

        def done(_result: Any, error: BaseException | None) -> None:
            if error is not None:
                self._say(str(error))

        self._run(self.app.client.mirror_input(self.peer, action), done)

    def type_text(self) -> None:
        text = self.text.get()
        if text and self.running:
            self.text.delete(0, "end")
            self.send({"type": "text", "text": text})

    def stop(self) -> None:
        """Stop sharing (leaving the page does this too)."""
        if not self.running:
            return
        self.running = False
        self.session += 1
        self.size = (0, 0)
        peer = self.peer
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(self.app.client.mirror_stop(peer),
                                             self.app.runtime.loop)
        with contextlib.suppress(tk.TclError):
            self._refresh()
            self._say("Stoppet. Tryk Start for at se skærmen igen.")


def open_mirror(app: Any, peer: Peer) -> None:
    """The device menu's "Vis og styr skærmen…": open the "Styr telefon" page and start."""
    app.mirror_peer_id = peer.device_id
    app.show_page("mirror")
    app.mirror_view.start()
