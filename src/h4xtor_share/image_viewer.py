"""Received pictures inside the app: small previews on the Overførsler page and a
built-in photo viewer (a gallery laid over the page area, not a separate program).

Pillow does the decoding (JPEG, WebP, BMP …, and it turns phone photos upright from
their EXIF data). Without Pillow, Tk's own PNG/GIF reader is used, so a missing
library never breaks the page: the row just keeps its arrow icon.
"""

from __future__ import annotations

import base64
import contextlib
import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .ui_kit import Button, Theme

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"})
TK_SUFFIXES = frozenset({".png", ".gif"})  # what Tk reads without Pillow
MAX_PREVIEW_BYTES = 80 * 1024 * 1024  # never decode a huge or broken file on the UI thread


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def _pillow() -> Any:
    try:
        from PIL import Image, ImageOps, ImageTk
    except ImportError:
        return None
    return Image, ImageOps, ImageTk


def load_photo(
    master: tk.Misc, path: str | Path, width: int, height: int, *, cover: bool = False
) -> Any | None:
    """A Tk image of ``path`` that fits in ``width`` × ``height`` (or fills it, cropped,
    with ``cover``). ``None`` when the file is missing, too big or not a picture."""
    path = Path(path)
    if width <= 0 or height <= 0 or not is_image(path):
        return None
    try:
        if not path.is_file() or path.stat().st_size > MAX_PREVIEW_BYTES:
            return None
    except OSError:
        return None
    pillow = _pillow()
    if pillow is not None:
        image_mod, ops, image_tk = pillow
        try:
            with image_mod.open(path) as picture:
                with contextlib.suppress(Exception):
                    picture.draft("RGB", (width * 2, height * 2))  # fast JPEG downscale
                picture = ops.exif_transpose(picture)
                picture = picture.convert("RGBA" if picture.mode in {"RGBA", "LA", "P"} else "RGB")
                if cover:
                    picture = ops.fit(picture, (width, height), image_mod.LANCZOS)
                else:
                    picture.thumbnail((width, height), image_mod.LANCZOS)
                return image_tk.PhotoImage(picture, master=master)
        except Exception:  # noqa: BLE001 - a broken file just gets no preview
            return None
    if path.suffix.lower() not in TK_SUFFIXES:
        return None
    try:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        image = tk.PhotoImage(master=master, data=data)
    except (OSError, tk.TclError):
        return None
    # Tk can only shrink in whole steps.
    shrink = max(1, -(-image.width() // width), -(-image.height() // height))
    if cover:
        shrink = max(1, min(image.width() // width, image.height() // height))
    return image.subsample(shrink) if shrink > 1 else image


def image_size_text(path: str | Path) -> str:
    """'4032 × 3024' when Pillow can read the header, else ''."""
    pillow = _pillow()
    if pillow is None:
        return ""
    with contextlib.suppress(Exception), pillow[0].open(path) as picture:
        width, height = pillow[1].exif_transpose(picture).size
        return f"{width} × {height}"
    return ""


class ImageViewer(tk.Frame):
    """A dark photo viewer laid over the page area. ← / → (or the arrows and the strip
    of small pictures) browse the received pictures; Esc or ✕ closes it."""

    THUMB = 64

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        paths: Sequence[str],
        index: int = 0,
        *,
        on_open: Callable[[str], None] | None = None,
        on_reveal: Callable[[str], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        c, px = theme.c, theme.px
        super().__init__(parent, bg=c["bg"])
        self.theme = theme
        self.paths = [str(p) for p in paths]
        self.index = max(0, min(index, len(self.paths) - 1))
        self.on_open = on_open
        self.on_reveal = on_reveal
        self.on_close = on_close
        self._image: Any = None
        self._thumbs: list[Any] = []
        self._thumb_cells: list[tk.Canvas] = []
        self._shown_size = (0, 0)
        self._closed = False

        top = tk.Frame(self, bg=c["bg"])
        top.pack(fill="x", padx=px(24), pady=(px(16), px(10)))
        info = tk.Frame(top, bg=c["bg"])
        info.pack(side="left", fill="x", expand=True)
        self.title = tk.Label(info, text="", bg=c["bg"], fg=c["text"], anchor="w",
                              font=theme.font(12, "bold"))
        self.title.pack(fill="x")
        self.meta = tk.Label(info, text="", bg=c["bg"], fg=c["muted"], anchor="w",
                             font=theme.font(9))
        self.meta.pack(fill="x")
        Button(top, theme, "", self.close, kind="ghost", icon="✕", size="sm",
               width=32).pack(side="right", padx=(px(6), 0))
        if on_reveal is not None:
            Button(top, theme, "Vis i mappe", lambda: on_reveal(self.current), kind="ghost",
                   size="sm").pack(side="right", padx=(px(6), 0))
        if on_open is not None:
            Button(top, theme, "Åbn", lambda: on_open(self.current),
                   size="sm").pack(side="right")

        self.strip = tk.Frame(self, bg=c["bg"])
        self.strip.pack(side="bottom", fill="x", padx=px(24), pady=(px(8), px(16)))

        stage = tk.Frame(self, bg=c["bg"])
        stage.pack(fill="both", expand=True, padx=px(12))
        self.prev_button = Button(stage, theme, "", self.previous, kind="ghost", icon="‹",
                                  width=40)
        self.prev_button.pack(side="left")
        self.next_button = Button(stage, theme, "", self.next, kind="ghost", icon="›", width=40)
        self.next_button.pack(side="right")
        self.canvas = tk.Canvas(stage, bg=c["sidebar"], highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True, padx=px(8))
        self.canvas.bind("<Configure>", lambda _e: self._draw())
        self.canvas.bind("<Double-Button-1>", lambda _e: on_open and on_open(self.current))

        self._build_strip()
        # The main window has no other use for these keys; they are removed on close.
        self._keys = ("<Left>", "<Right>", "<Escape>")
        root = self.winfo_toplevel()
        root.bind("<Left>", lambda _e: self.previous())
        root.bind("<Right>", lambda _e: self.next())
        root.bind("<Escape>", lambda _e: self.close())
        self.show(self.index)

    @property
    def current(self) -> str:
        return self.paths[self.index] if self.paths else ""

    def _build_strip(self) -> None:
        c, px = self.theme.c, self.theme.px
        size = px(self.THUMB)
        # Only the nearest pictures: a long history must not decode hundreds of files.
        for i, path in enumerate(self.paths[:40]):
            cell = tk.Canvas(self.strip, width=size + 4, height=size + 4, bg=c["bg"],
                             highlightthickness=0, bd=0, cursor="hand2")
            cell.pack(side="left", padx=(0, px(6)))
            thumb = load_photo(self, path, size, size, cover=True)
            self._thumbs.append(thumb)
            if thumb is not None:
                cell.create_image(2 + size / 2, 2 + size / 2, image=thumb)
            else:
                cell.create_text(2 + size / 2, 2 + size / 2, text="?", fill=c["muted"],
                                 font=self.theme.font(12, "bold"))
            cell.bind("<Button-1>", lambda _e, i=i: self.show(i))
            self._thumb_cells.append(cell)

    def show(self, index: int) -> None:
        if not self.paths:
            return
        self.index = index % len(self.paths)
        path = Path(self.current)
        c = self.theme.c
        self.title.configure(text=path.name)
        size = image_size_text(path)
        parts = [f"{self.index + 1} af {len(self.paths)}"]
        if size:
            parts.append(size)
        with contextlib.suppress(OSError):
            parts.append(_format_bytes(path.stat().st_size))
        self.meta.configure(text="  ·  ".join(parts))
        many = len(self.paths) > 1
        for button in (self.prev_button, self.next_button):
            button.set_enabled(many)
        for i, cell in enumerate(self._thumb_cells):
            cell.delete("ring")
            if i == self.index:
                w = int(cell.cget("width"))
                cell.create_rectangle(1, 1, w - 1, w - 1, outline=c["accent"], width=2,
                                      tags=("ring",))
        self._shown_size = (0, 0)
        self._draw()

    def _draw(self) -> None:
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 20 or height < 20:
            width, height = 640, 420  # not laid out yet; redrawn on <Configure>
        if (width, height) == self._shown_size and self._image is not None:
            return
        self._shown_size = (width, height)
        c = self.theme.c
        self.canvas.delete("all")
        self._image = load_photo(self, self.current, width, height)
        if self._image is None:
            self.canvas.create_text(width / 2, height / 2, fill=c["muted"],
                                    font=self.theme.font(11),
                                    text="Billedet kan ikke vises her.\n"
                                         "Tryk \"Åbn\" for at se det.",
                                    justify="center")
            return
        self.canvas.create_image(width / 2, height / 2, image=self._image)

    def previous(self) -> None:
        if len(self.paths) > 1:
            self.show(self.index - 1)

    def next(self) -> None:
        if len(self.paths) > 1:
            self.show(self.index + 1)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        root = self.winfo_toplevel()
        for sequence in self._keys:
            with contextlib.suppress(tk.TclError):
                root.unbind(sequence)
        self._image = None
        self._thumbs.clear()
        if self.on_close is not None:
            self.on_close()
        with contextlib.suppress(tk.TclError):
            self.destroy()


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
