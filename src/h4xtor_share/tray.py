"""System tray icon (Windows) built on pystray.

The tray keeps h4xtor-share running in the background so files, links and
clipboard text keep arriving after the window is closed. Everything here is
optional: when pystray/Pillow are missing the app simply has no tray icon.
"""

from __future__ import annotations

import contextlib
import platform
import threading
from collections.abc import Callable
from typing import Any


def tray_supported() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def make_icon_image(size: int = 64, color: str = "#C96442") -> Any:
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = size // 4
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=color)
    line = max(2, size // 12)
    mid = size // 2
    # Two opposing arrows: "share both ways".
    draw.line((size * 0.28, size * 0.38, size * 0.72, size * 0.38), fill="white", width=line)
    draw.polygon(
        [(size * 0.72, size * 0.26), (size * 0.84, size * 0.38), (size * 0.72, size * 0.50)],
        fill="white",
    )
    draw.line((size * 0.28, size * 0.64, size * 0.72, size * 0.64), fill="white", width=line)
    draw.polygon(
        [(size * 0.28, size * 0.52), (size * 0.16, size * 0.64), (size * 0.28, size * 0.76)],
        fill="white",
    )
    del mid
    return image


class TrayIcon:
    def __init__(
        self,
        on_open: Callable[[], None],
        on_pair: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self.on_open = on_open
        self.on_pair = on_pair
        self.on_quit = on_quit
        self._icon: Any = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if not tray_supported():
            return False
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Åbn h4xtor share", lambda: self.on_open(), default=True),
            pystray.MenuItem("Forbind ny enhed…", lambda: self.on_pair()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Afslut", lambda: self.on_quit()),
        )
        self._icon = pystray.Icon("h4xtor-share", make_icon_image(), "h4xtor share", menu)
        self._thread = threading.Thread(target=self._icon.run, name="h4xtor-tray", daemon=True)
        self._thread.start()
        return True

    def notify(self, message: str, title: str = "h4xtor share") -> None:
        if self._icon is None:
            return
        with contextlib.suppress(Exception):
            self._icon.notify(message, title)

    def stop(self) -> None:
        if self._icon is None:
            return
        with contextlib.suppress(Exception):
            self._icon.stop()
        self._icon = None
