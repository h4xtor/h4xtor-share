"""The phone's screen, live, in a window on the PC – steered with the mouse and keyboard.

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
from h4xtor_share.ui_kit import Button

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


class MirrorWindow(tk.Toplevel):
    def __init__(self, app: Any, peer: Peer) -> None:
        super().__init__(app)
        self.app, self.peer, self.theme = app, peer, app.theme
        c, px = self.theme.c, self.theme.px
        self.title(f"{peer.name} – skærm")
        self.configure(bg=c["bg"])
        self.seq = 0
        self.size = (0, 0)  # the picture as shown
        self.closed = False
        self._press: tuple[float, float, float] | None = None
        self._image: Any = None
        try:
            from PIL import Image, ImageTk  # noqa: F401  (Windows builds ship Pillow)

            self.format = "jpeg"
        except ImportError:
            self.format = "png"  # Tk reads PNG itself

        bar = tk.Frame(self, bg=c["bg"])
        bar.pack(fill="x", padx=px(10), pady=(px(10), px(6)))
        for label, kind in (("◀  Tilbage", "back"), ("●  Hjem", "home"), ("▢  Apps", "recents")):
            Button(bar, self.theme, label, lambda k=kind: self.send({"type": k}),
                   kind="secondary", size="sm").pack(side="left", padx=(0, px(6)))
        Button(bar, self.theme, "Stop", self.close, kind="danger", size="sm").pack(side="right")
        self.status = tk.Label(self, text="Tryk “Start nu” på telefonen for at dele skærmen …",
                               bg=c["bg"], fg=c["muted"], font=self.theme.font(9))
        self.status.pack(fill="x", padx=px(10))
        self.canvas = tk.Canvas(self, bg="#000000", highlightthickness=0, cursor="hand2",
                                width=px(360), height=px(640))
        self.canvas.pack(padx=px(10), pady=px(8))
        typing = tk.Frame(self, bg=c["bg"])
        typing.pack(fill="x", padx=px(10), pady=(0, px(10)))
        self.text = tk.Entry(typing, bg=c["entry"], fg=c["text"], insertbackground=c["text"],
                             relief="flat", font=self.theme.font(10))
        self.text.pack(side="left", fill="x", expand=True, ipady=px(6))
        self.text.bind("<Return>", lambda _e: self.type_text())
        Button(typing, self.theme, "Skriv på telefonen", self.type_text, kind="primary",
               size="sm").pack(side="left", padx=(px(6), 0))

        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.canvas.bind("<Button-3>", lambda _e: self.send({"type": "back"}))
        self.canvas.bind("<MouseWheel>", lambda e: self.send(wheel(e.delta)))
        self.canvas.bind("<Button-4>", lambda _e: self.send(wheel(120)))
        self.canvas.bind("<Button-5>", lambda _e: self.send(wheel(-120)))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._run(self.app.client.mirror_start(peer, self.format), self._started)

    # ------------------------------------------------------------ plumbing
    def _run(self, coroutine: Any, done: Any) -> None:
        """Run on the app's network loop; hand the outcome back to Tk (polled, thread-safe)."""
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, self.app.runtime.loop)

        def check() -> None:
            if self.closed:
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

    def _started(self, _result: Any, error: BaseException | None) -> None:
        if error is not None:
            self._say(f"Kunne ikke starte: {error}")
            return
        self._next()

    def _next(self) -> None:
        self._run(self.app.client.mirror_frame(self.peer, self.seq), self._frame)

    def _frame(self, frame: dict[str, Any] | None, error: BaseException | None) -> None:
        if error is not None:
            self._say(f"Forbindelsen drillede: {error}")
            self.after(1000, self._next)
            return
        assert frame is not None
        if not frame.get("active"):
            if frame.get("waiting"):
                self._say("Tryk “Start nu” på telefonen for at dele skærmen …")
                self.after(600, self._next)
            else:
                self._say("Skærmdelingen er stoppet på telefonen.")
            return
        if frame.get("image") and int(frame.get("seq", 0)) != self.seq:
            self.seq = int(frame["seq"])
            self._show(base64.b64decode(frame["image"]), frame.get("format", "png"))
            self._say("Klik for at trykke · træk for at swipe · hjul ruller · højreklik er Tilbage")
        self._next()

    def _show(self, data: bytes, kind: str) -> None:
        tall = max(200, int(self.winfo_screenheight() * 0.72))
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
            self.canvas.configure(width=size[0], height=size[1])
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
        def done(_result: Any, error: BaseException | None) -> None:
            if error is not None:
                self._say(str(error))

        self._run(self.app.client.mirror_input(self.peer, action), done)

    def type_text(self) -> None:
        text = self.text.get()
        if text:
            self.text.delete(0, "end")
            self.send({"type": "text", "text": text})

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            with contextlib.suppress(Exception):
                asyncio.run_coroutine_threadsafe(self.app.client.mirror_stop(self.peer),
                                                 self.app.runtime.loop)
        with contextlib.suppress(tk.TclError):
            self.destroy()


def open_mirror(app: Any, peer: Peer) -> None:
    """Open (or bring forward) the screen window for this phone."""
    windows: dict[str, MirrorWindow] = app.__dict__.setdefault("_mirror_windows", {})
    window = windows.get(peer.device_id)
    if window is not None and not window.closed and window.winfo_exists():
        window.lift()
        return
    windows[peer.device_id] = MirrorWindow(app, peer)

