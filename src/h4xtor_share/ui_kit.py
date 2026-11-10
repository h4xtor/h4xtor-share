"""Small Tk widget kit used by the desktop app.

Plain Tk widgets look dated, so the app draws its own rounded buttons,
cards, toggles, pills and progress bars on canvases. Everything is themed
from one palette (light and dark) and scaled for high-DPI screens.
"""

from __future__ import annotations

import contextlib
import platform
import time
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from typing import Any

# The "Graphite" identity: near-black graphite surfaces separated by hairlines, one electric
# blue for the action that matters and a restrained cyan for focus and live activity.
# Every colour is a semantic token (the light palette mirrors the dark one key for key), and
# text colours keep at least 4.5:1 against the surfaces they sit on.
LIGHT = {
    "bg": "#F6F7F9",
    "sidebar": "#EEF0F3",
    "chrome": "#EEF0F3",
    "card": "#FFFFFF",
    "card_hover": "#F3F5F8",
    "border": "#E2E5EA",
    "border_strong": "#C5CAD3",
    "text": "#0D1015",
    "muted": "#4A5261",
    "faint": "#5E6675",
    "accent": "#1D5BD8",
    "accent_hover": "#174BB5",
    "accent_press": "#123C92",
    "button": "#1D5BD8",
    "button_hover": "#174BB5",
    "accent_soft": "#E0EAFC",
    "accent_text": "#FFFFFF",
    "accent2": "#0891B2",
    "accent3": "#B45309",
    "success": "#0F7A4A",
    "success_soft": "#DDF3E7",
    "warning": "#8A5A10",
    "warning_soft": "#FBEFD9",
    "danger": "#B42318",
    "danger_soft": "#FBE4E1",
    "neutral_soft": "#ECEEF2",
    "nav_active": "#DFE3EA",
    "nav_hover": "#E7EAEF",
    "track": "#DCE0E6",
    "entry": "#FFFFFF",
    "shadow": "#DDE1E7",
    "hero_top": "#D8E4FA",
    "glow": "#3B82F6",
}

DARK = {
    "bg": "#0B0C0E",
    "sidebar": "#08090A",
    "chrome": "#08090A",
    "card": "#121317",
    "card_hover": "#181A1F",
    "border": "#1F2228",
    "border_strong": "#2E323B",
    "text": "#EDEEF1",
    "muted": "#A0A6B2",
    "faint": "#7D8492",
    "accent": "#4C8DFF",
    "accent_hover": "#6FA5FF",
    "accent_press": "#1848B8",
    "button": "#2563EB",
    "button_hover": "#2E6BF0",
    "accent_soft": "#111D36",
    "accent_text": "#FFFFFF",
    "accent2": "#22D3EE",
    "accent3": "#FF9F1A",
    "success": "#34D399",
    "success_soft": "#0E2A20",
    "warning": "#FBBF24",
    "warning_soft": "#2E2410",
    "danger": "#F87171",
    "danger_soft": "#33191B",
    "neutral_soft": "#181A1F",
    "nav_active": "#17191E",
    "nav_hover": "#101216",
    "track": "#23262D",
    "entry": "#0E0F12",
    "shadow": "#050506",
    "hero_top": "#0E1730",
    "glow": "#2563EB",
}

# One spacing scale and one radius scale for the whole app (logical px, scaled by Theme.px).
SPACE = (4, 8, 12, 16, 24, 32, 40)
RADIUS = {"sm": 6, "md": 8, "lg": 12}
PAGE_INSET = 40  # every page's content starts this far from the page edge
PAGE_MAX = 1120  # ... and never grows wider than this, however big the window

# Avatar colours: bright enough to read a dark letter on (see Avatar).
PLATFORM_STYLE = {
    "android": ("#34D399", "A"),
    "windows": ("#5B9BFF", "W"),
    "linux": ("#FBBF24", "L"),
    "darwin": ("#A0A6B2", "M"),
    "macos": ("#A0A6B2", "M"),
    "all": ("#22D3EE", "★"),
}
AVATAR_LETTER = "#08090A"
# The drawn icon each platform gets on its device tile.
PLATFORM_ICON = {"android": "phone", "windows": "monitor", "linux": "monitor",
                 "darwin": "monitor", "macos": "monitor", "all": "grid"}


def prefers_reduced_motion() -> bool:
    """True when the system asks apps to hold back on animation (Windows: "Animation
    effects" switched off). Other systems have no setting Tk can read, so: False."""
    if platform.system() != "Windows":
        return False
    with contextlib.suppress(Exception):
        import ctypes

        enabled = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return not enabled.value
    return False


class Theme:
    def __init__(self, root: tk.Misc, dark: bool) -> None:
        self.dark = dark
        self.c = dict(DARK if dark else LIGHT)
        # Short hover/slide animations; off when the system or the user asks for less motion.
        self.motion = not prefers_reduced_motion()
        try:
            self.scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
        except tk.TclError:
            self.scale = 1.0
        families = set(tkfont.families(root))
        self.family = next(
            (
                name
                for name in (
                    "Segoe UI Variable Text",
                    "Segoe UI",
                    "SF Pro Text",
                    "Helvetica Neue",
                    "Inter",
                    "Cantarell",
                    "Noto Sans",
                    "DejaVu Sans",
                )
                if name in families
            ),
            "TkDefaultFont",
        )
        self.display_family = next(
            (
                name
                for name in ("Segoe UI Variable Display", "Segoe UI Semibold", "SF Pro Display")
                if name in families
            ),
            self.family,
        )
        self.mono = next(
            (
                name
                for name in ("Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono")
                if name in families
            ),
            "TkFixedFont",
        )
        self.symbol = next(
            (
                name
                for name in ("Segoe UI Symbol", "Segoe Fluent Icons", "DejaVu Sans")
                if name in families
            ),
            self.family,
        )
        # Claude.ai pairs a serif display face with a clean sans for UI text.
        self.serif = next(
            (
                name
                for name in ("Georgia", "Cambria", "Iowan Old Style", "DejaVu Serif", "Noto Serif")
                if name in families
            ),
            self.display_family,
        )
        # Launcher headings: a sporty, slightly condensed face for the big uppercase titles.
        self.heading_family = next(
            (
                name
                for name in ("Bahnschrift", "Segoe UI Black", "Arial Black", "Inter Display")
                if name in families
            ),
            self.display_family,
        )
        self._fonts: dict[tuple[str, int, str], tkfont.Font] = {}

    def px(self, value: float) -> int:
        return int(round(value * self.scale))

    def font(self, size: int, weight: str = "normal", family: str | None = None) -> tkfont.Font:
        key = (family or self.family, size, weight)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family=key[0], size=size, weight=weight)
        return self._fonts[key]

    def title_font(self, size: int) -> tkfont.Font:
        # The mix design: tight, bold sans headings (no serif).
        return self.font(size, "bold", self.display_family)

    def ui_title_font(self, size: int) -> tkfont.Font:
        return self.font(size, "bold", self.display_family)

    def hero_font(self, size: int) -> tkfont.Font:
        """Big uppercase launcher titles (game names on Battle.net)."""
        return self.font(size, "bold", self.heading_family)


def round_rect(
    canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs: Any
) -> int:
    radius = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


_GLASS_CACHE: dict[tuple[Any, ...], tk.PhotoImage] = {}


def glass_image(
    master: tk.Misc, width: int, height: int, radius: float, fill: str,
    bg: str | tuple[str, str, str, str], ring: str | None = None, ring_width: float = 1.0,
    shine: bool = True, light: float = 0.20,
) -> tk.PhotoImage:
    """A flat rounded rectangle with smooth (anti-aliased) edges and an optional hairline
    ring: the surface of every button, card, chip and switch. Tk cannot smooth polygon
    edges, so this paints each edge pixel by how much of it the shape covers. ``bg`` may be
    four colours (top-left, top-right, bottom-left, bottom-right) when the widget sits on
    artwork: the corners then blend into it instead of showing a box. Cached per look and
    size.

    Only the corners and edges are worked out pixel by pixel: the inside is one fill and
    the straight edges repeat, so even a card that fills the window costs next to nothing.
    ``shine``/``light`` are kept for call-site compatibility and ignored (flat surfaces)."""
    import math

    key = (master.tk, width, height, radius, fill, bg, ring, ring_width, shine, light)  # per app
    image = _GLASS_CACHE.get(key)
    if image is not None:
        return image
    if len(_GLASS_CACHE) > 400:
        _GLASS_CACHE.clear()

    def tone(color: str) -> list[float]:  # any Tk colour (a name too) as 0-255 floats
        return [v / 257 for v in master.winfo_rgb(color)]

    base, edge_tone = tone(fill), tone(ring or fill)
    uniform = isinstance(bg, str) or len(set(bg)) == 1
    corners = [tone(c) for c in ((bg,) * 4 if isinstance(bg, str) else bg)]
    radius = max(0.0, min(radius, width / 2, height / 2))
    half_w, half_h = width / 2, height / 2

    def shade(x: int, y: int) -> str:
        qx = abs(x + 0.5 - half_w) - (half_w - radius)
        qy = abs(y + 0.5 - half_h) - (half_h - radius)
        d = math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - radius
        cover = 0.5 - d
        color = base
        if ring and d > -ring_width - 0.5:  # the outline, smoothed on its inner side
            k = min(1.0, d + ring_width + 0.5)
            color = [a + (b - a) * k for a, b in zip(base, edge_tone, strict=True)]
        if cover < 1:  # on the edge, or outside: blend into what is behind
            if uniform:
                back = corners[0]
            else:
                u, v = (x + 0.5) / width, (y + 0.5) / height
                left = [a + (b - a) * v for a, b in zip(corners[0], corners[2], strict=True)]
                right = [a + (b - a) * v for a, b in zip(corners[1], corners[3], strict=True)]
                back = [a + (b - a) * u for a, b in zip(left, right, strict=True)]
            if cover <= 0:
                return "#" + "".join(_HEX[max(0, min(255, int(c)))] for c in back)
            color = [b + (a - b) * cover for a, b in zip(color, back, strict=True)]
        return "#" + "".join(_HEX[max(0, min(255, int(c)))] for c in color)

    def block(xs: Any, ys: Any) -> str:
        return " ".join("{" + " ".join(shade(x, y) for x in xs) + "}" for y in ys)

    # The round ends need working out; between them every pixel of a row is the same, and
    # between the top and bottom bands every row is the same.
    edge = min(width // 2, int(radius) + 3)
    band = min(height // 2, int(radius) + 3)
    image = tk.PhotoImage(master=master, width=width, height=height)
    if not uniform or width <= 2 * edge or height <= 2 * band:
        rows = []
        for y in range(height):
            middle = [shade(width // 2, y)] * (width - 2 * edge)
            row = [shade(x, y) for x in range(edge)] + middle + [
                shade(x, y) for x in range(width - edge, width)]
            rows.append("{" + " ".join(row) + "}")
        image.put(" ".join(rows))
    else:
        mid_x, mid_y = width // 2, height // 2
        image.put(shade(mid_x, mid_y), to=(0, 0, width, height))
        for top in (0, height - band):
            ys = range(top, top + band)
            image.put(block(range(edge), ys), to=(0, top))
            image.put(block(range(width - edge, width), ys), to=(width - edge, top))
            image.put(block((mid_x,), ys), to=(edge, top, width - edge, top + band))
        image.put(block(range(edge), (mid_y,)), to=(0, band, edge, height - band))
        image.put(block(range(width - edge, width), (mid_y,)),
                  to=(width - edge, band, width, height - band))
    _GLASS_CACHE[key] = image
    return image


# ---------------------------------------------------------------------------- icons
# One icon family for the whole app: thin rounded strokes on a 24-unit grid. Unicode symbols
# (⇄ ◈ ▯ …) look different on every system — and some are missing altogether — so the icons
# are drawn here and smoothed pixel by pixel, like the buttons.
# Shapes: ("l", x1, y1, x2, y2, …) a polyline · ("c", cx, cy, r) a ring · ("d", cx, cy, r) a
# filled dot · ("a", cx, cy, r, from°, to°) an arc, clockwise with 0° pointing right ·
# ("r", x1, y1, x2, y2, radius) a rounded box · ("e", cx, cy, r) rubs a dot back out.
ICONS: dict[str, tuple[tuple[Any, ...], ...]] = {
    "send": (("l", 21, 3, 10.5, 13.5), ("l", 21, 3, 14.5, 21, 10.5, 13.5, 3, 9.5, 21, 3)),
    "transfers": (("l", 8, 20, 8, 4), ("l", 4, 8, 8, 4, 12, 8),
                  ("l", 16, 4, 16, 20), ("l", 12, 16, 16, 20, 20, 16)),
    "clipboard": (("r", 5, 4.5, 19, 21, 2.5), ("e", 12, 4.5, 3.6), ("r", 9, 2.5, 15, 6.5, 1.5)),
    "phone": (("r", 6.5, 2.5, 17.5, 21.5, 2.8), ("l", 11, 18, 13, 18)),
    "bell": (("a", 12, 10.5, 6, 180, 360), ("l", 6, 10.5, 6, 14, 4, 17, 20, 17, 18, 14, 18, 10.5),
             ("a", 12, 19.3, 2, 15, 165)),
    "message": (("r", 3, 4, 21, 17, 2.8), ("e", 10, 17, 2.4), ("l", 7.5, 17, 7.5, 21, 12.5, 17)),
    "remote": (("c", 12, 12, 7.5), ("d", 12, 12, 1.8), ("l", 12, 2, 12, 5), ("l", 12, 19, 12, 22),
               ("l", 2, 12, 5, 12), ("l", 19, 12, 22, 12)),
    "wifi": (("a", 12, 19, 13.5, 229, 311), ("a", 12, 19, 9, 229, 311),
             ("a", 12, 19, 4.6, 229, 311), ("d", 12, 19, 1.4)),
    "globe": (("c", 12, 12, 9), ("l", 3, 12, 21, 12), ("a", 20, 12, 12.04, 131.6, 228.4),
              ("a", 4, 12, 12.04, 311.6, 408.4)),
    "merge": (("l", 3.5, 6, 8.5, 6, 13.5, 12, 20, 12), ("l", 3.5, 18, 8.5, 18, 13.5, 12),
              ("l", 17, 9, 20, 12, 17, 15)),
    "history": (("c", 12, 12, 9), ("l", 12, 7, 12, 12, 15.5, 14)),
    "settings": (("l", 4, 7.5, 20, 7.5), ("l", 4, 16.5, 20, 16.5), ("e", 9, 7.5, 3.4),
                 ("c", 9, 7.5, 2.4), ("e", 15, 16.5, 3.4), ("c", 15, 16.5, 2.4)),
    "plus": (("l", 12, 5, 12, 19), ("l", 5, 12, 19, 12)),
    "search": (("c", 11, 11, 6.5), ("l", 16, 16, 20.5, 20.5)),
    "chevron-down": (("l", 7, 10, 12, 15, 17, 10),),
    "chevron-right": (("l", 10, 7, 15, 12, 10, 17),),
    "arrow-up": (("l", 12, 19, 12, 5), ("l", 6, 11, 12, 5, 18, 11)),
    "arrow-down": (("l", 12, 5, 12, 19), ("l", 6, 13, 12, 19, 18, 13)),
    "file": (("l", 14, 3, 6.5, 3, 6.5, 21, 18.5, 21, 18.5, 7.5, 14, 3),
             ("l", 14, 3, 14, 7.5, 18.5, 7.5)),
    "folder": (("l", 3, 6, 9, 6, 11, 8.5, 21, 8.5, 21, 19, 3, 19, 3, 6),),
    "link": (("l", 9.5, 14.5, 14.5, 9.5),
             ("l", 11, 7, 13, 5, 16, 4.2, 19, 5, 19.8, 8, 19, 11, 17, 13),
             ("l", 13, 17, 11, 19, 8, 19.8, 5, 19, 4.2, 16, 5, 13, 7, 11)),
    "copy": (("l", 15.5, 9, 15.5, 5, 4.5, 5, 4.5, 16, 9, 16), ("r", 9, 9, 20, 20, 2)),
    "qr": (("r", 4, 4, 10, 10, 1.2), ("r", 14, 4, 20, 10, 1.2), ("r", 4, 14, 10, 20, 1.2),
           ("d", 15, 15, 1.1), ("d", 19, 19, 1.1), ("d", 19, 15, 1.1), ("d", 15, 19, 1.1)),
    "bluetooth": (("l", 7, 7.5, 17, 16.5, 12, 21, 12, 3, 17, 7.5, 7, 16.5),),
    "bolt": (("l", 13, 2.5, 5, 13.5, 11.5, 13.5, 10.5, 21.5, 19, 10.5, 12.5, 10.5, 13, 2.5),),
    "more": (("d", 6, 12, 1.5), ("d", 12, 12, 1.5), ("d", 18, 12, 1.5)),
    "x": (("l", 6, 6, 18, 18), ("l", 18, 6, 6, 18)),
    "check": (("l", 5, 12.5, 10, 17.5, 19, 7),),
    "monitor": (("r", 3, 4, 21, 16, 2), ("l", 8.5, 20, 15.5, 20), ("l", 12, 16, 12, 20)),
    "grid": (("r", 4, 4, 10.5, 10.5, 1.5), ("r", 13.5, 4, 20, 10.5, 1.5),
             ("r", 4, 13.5, 10.5, 20, 1.5), ("r", 13.5, 13.5, 20, 20, 1.5)),
    "download": (("l", 12, 4, 12, 15), ("l", 7, 10.5, 12, 15.5, 17, 10.5),
                 ("l", 4, 17, 4, 20, 20, 20, 20, 17)),
    "play": (("l", 8, 5, 19, 12, 8, 19, 8, 5),),
    "command": (("l", 9, 6, 9, 18), ("l", 15, 6, 15, 18), ("l", 6, 9, 18, 9), ("l", 6, 15, 18, 15),
                ("c", 6.5, 6.5, 2.5), ("c", 17.5, 6.5, 2.5), ("c", 6.5, 17.5, 2.5),
                ("c", 17.5, 17.5, 2.5)),
}
# Symbols the pages already pass as a button's icon, and the drawn icon each becomes.
GLYPH_ICONS = {"+": "plus", "＋": "plus", "↑": "arrow-up", "↓": "arrow-down", "▤": "folder",
               "⧉": "clipboard", "⚙": "settings", "⋯": "more", "✕": "x", "▾": "chevron-down",
               "▶": "play"}
_ICON_CACHE: dict[tuple[Any, ...], tk.PhotoImage] = {}


def icon_image(master: tk.Misc, name: str, size: int, color: str, bg: str,
               weight: float = 1.7) -> tk.PhotoImage:
    """The icon ``name`` as a ``size``-pixel image in ``color`` on ``bg``, with smooth
    edges. ``weight`` is the stroke on the 24-unit grid. Cached per look."""
    import math

    key = (master.tk, name, size, color, bg, weight)
    image = _ICON_CACHE.get(key)
    if image is not None:
        return image
    if len(_ICON_CACHE) > 600:
        _ICON_CACHE.clear()
    k = size / 24.0
    half = max(1.15, weight * k) / 2
    ink = [v / 257 for v in master.winfo_rgb(color)]
    paper = [v / 257 for v in master.winfo_rgb(bg)]

    def segment(x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> float:
        dx, dy = x2 - x1, y2 - y1
        length = dx * dx + dy * dy
        t = 0.0 if not length else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length))
        return math.hypot(x - x1 - t * dx, y - y1 - t * dy)

    def cover(shape: tuple[Any, ...], x: float, y: float) -> float:
        kind = shape[0]
        v = [n * k for n in shape[1:]] if kind != "a" else [n * k for n in shape[1:4]]
        if kind == "l":
            d = min(segment(x, y, v[i], v[i + 1], v[i + 2], v[i + 3])
                    for i in range(0, len(v) - 2, 2))
        elif kind in "cde":
            d = math.hypot(x - v[0], y - v[1]) - v[2]
            if kind != "c":
                return max(0.0, min(1.0, 0.5 - d))
            d = abs(d)
        elif kind == "a":
            start, end = shape[4], shape[5]
            angle = math.degrees(math.atan2(y - v[1], x - v[0])) % 360
            if (angle - start) % 360 <= end - start:
                d = abs(math.hypot(x - v[0], y - v[1]) - v[2])
            else:
                d = min(math.hypot(x - v[0] - v[2] * math.cos(math.radians(a)),
                                   y - v[1] - v[2] * math.sin(math.radians(a)))
                        for a in (start, end))
        else:  # "r": the outline of a rounded box
            radius = v[4]
            qx = abs(x - (v[0] + v[2]) / 2) - ((v[2] - v[0]) / 2 - radius)
            qy = abs(y - (v[1] + v[3]) / 2) - ((v[3] - v[1]) / 2 - radius)
            d = abs(math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - radius)
        return max(0.0, min(1.0, half + 0.5 - d))

    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            pixel = paper
            for shape in ICONS[name]:
                amount = cover(shape, px + 0.5, py + 0.5)
                if amount > 0:
                    target = paper if shape[0] == "e" else ink
                    pixel = [a + (b - a) * amount for a, b in zip(pixel, target, strict=True)]
            row.append("#" + "".join(_HEX[max(0, min(255, int(c)))] for c in pixel))
        rows.append("{" + " ".join(row) + "}")
    image = tk.PhotoImage(master=master, width=size, height=size)
    image.put(" ".join(rows))
    _ICON_CACHE[key] = image
    return image


def set_dark_titlebar(window: tk.Misc, dark: bool) -> None:
    """Match the Windows 10/11 title bar to the app theme."""
    if platform.system() != "Windows":
        return
    with contextlib.suppress(Exception):
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            if (
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                )
                == 0
            ):
                break


class Button(tk.Canvas):
    """The app's button, drawn on a canvas: a softly rounded rectangle with a hover, a
    pressed and a keyboard-focus state.

    Tab reaches every button; Enter or Space presses the focused one, which shows a cyan
    focus ring. A known symbol as ``icon`` (＋ ↑ ⚙ …) is drawn from the app's own icon
    family, and a label ending in ``▾`` gets a drawn chevron. Colours glide between the
    states in a few frames (unless the theme asks for no motion).
    """

    SIZES = {  # font size, horizontal padding, height
        "sm": (9, 10, 28),
        "md": (10, 13, 32),
        "lg": (10, 16, 38),
        "xl": (11, 22, 44),
    }
    FADE_MS = 24  # per frame; four frames = about 100 ms

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        text: str,
        command: Callable[[], Any] | None = None,
        *,
        kind: str = "secondary",
        icon: str = "",
        size: str = "md",
        width: int | None = None,
        bg: str | None = None,
    ) -> None:
        self.theme = theme
        self.kind = kind
        self.command = command
        self.enabled = True
        self.backdrop: tuple[str, str, str, str] | None = None  # artwork colours behind it
        self._hover = False
        self._pressed = False
        self._focused = False
        self._text = text
        self._icon = icon
        self._size = size
        font_size, pad, height = self.SIZES[size]
        bold = kind in {"primary", "danger"} or size == "xl"
        self._font = theme.font(font_size, "bold" if bold else "normal")
        self._pad = theme.px(pad)
        self._fixed = theme.px(width) if width else None
        self._height = theme.px(height)
        self._radius = theme.px(RADIUS["sm"] if size == "sm" else RADIUS["md"])
        self._glyph = theme.px(14 if size == "sm" else 16)  # drawn icon size
        self._shown: tuple[str, str, str] | None = None  # colours on screen right now
        self._fade_after: str | None = None
        self._parse()
        self._width = self._fixed or self._natural()
        background = bg if bg is not None else parent.cget("bg")
        super().__init__(
            parent,
            width=self._width,
            height=self._height,
            bg=background,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonPress-1>", lambda _e: self._set_pressed(True))
        self.bind("<ButtonRelease-1>", self._clicked)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.bind("<FocusOut>", lambda _e: self._set_focus(False))
        self.bind("<Destroy>", lambda _e: self._stop_fade(), add="+")
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, self._key_pressed)
        self._draw()

    def _parse(self) -> None:
        """Split the label into a drawn leading icon, the words and a drawn chevron."""
        text, icon = self._text, self._icon
        self._lead = GLYPH_ICONS.get(icon, "")
        self._chevron = False
        if not self._lead and text in GLYPH_ICONS:  # a button that is only a symbol
            self._lead, text = GLYPH_ICONS[text], ""
        elif text.endswith(" ▾"):
            self._chevron, text = True, text[:-2].rstrip()
        glyph = "" if self._lead else icon
        self._words = f"{glyph}  {text}" if glyph and text else (glyph or text)
        self._label = f"{icon}  {self._text}" if icon and self._text else (icon or self._text)

    def _natural(self) -> int:
        gap = self.theme.px(7)
        inner = self._font.measure(self._words) if self._words else 0
        if self._lead:
            inner += self._glyph + (gap if self._words else 0)
        if self._chevron:
            inner += self.theme.px(12) + self.theme.px(4)
        return inner + 2 * self._pad

    def _colors(self) -> tuple[str, str, str]:
        c = self.theme.c
        if not self.enabled:
            return c["neutral_soft"], c["border"], c["faint"]
        if self.kind == "primary":
            fill = (
                c["accent_press"] if self._pressed
                else c["button_hover"] if self._hover
                else c["button"]
            )
            # A hairline lighter than the fill: the button's edge catches a little light.
            return fill, mix_color("#FFFFFF", fill, 0.84), c["accent_text"]
        if self.kind == "danger":
            fill = c["danger"] if self._hover or self._pressed else c["danger_soft"]
            text = c["accent_text"] if self._hover or self._pressed else c["danger"]
            if not self.theme.dark and (self._hover or self._pressed):
                text = "#FFFFFF"
            return fill, mix_color(c["danger"], fill, 0.5), text
        if self.kind == "ghost":
            fill = (
                c["border"] if self._pressed
                else c["nav_active"] if self._hover
                else self.cget("bg")
            )
            return fill, fill, c["text"]
        if self.kind == "soft":
            fill = mix_color(c["accent_soft"], c["accent"], 0.14) if (
                self._hover or self._pressed) else c["accent_soft"]
            return fill, mix_color(c["accent"], fill, 0.70), c["accent"]
        fill = (
            c["border"] if self._pressed
            else c["card_hover"] if self._hover
            else c["neutral_soft"]
        )
        border = c["border_strong"] if self._hover else mix_color(
            c["border_strong"], c["border"], 0.5)
        return fill, border, c["text"]

    def _draw(self) -> None:
        """Move to the colours of the current state: at once, or gliding there in a few
        frames when the pointer moved on or off the button."""
        target = self._colors()
        glide = (self.theme.motion and self._shown is not None and self._shown != target
                 and not self._pressed and self.enabled and self.winfo_ismapped())
        self._stop_fade()
        if glide:
            self._fade(self._shown, target, 1)
        else:
            self._paint(target)

    def _stop_fade(self) -> None:
        if self._fade_after is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._fade_after)
            self._fade_after = None

    def _fade(self, start: tuple[str, str, str], target: tuple[str, str, str], step: int) -> None:
        self._fade_after = None
        steps = 4
        try:
            if step >= steps:
                self._paint(target)
                return
            k = step / steps
            self._paint(tuple(mix_color(a, b, k) for a, b in zip(start, target, strict=True)))
            self._fade_after = self.after(self.FADE_MS,
                                          lambda: self._fade(start, target, step + 1))
        except tk.TclError:
            return
        except ValueError:  # a named system colour cannot be blended: jump to the end
            with contextlib.suppress(tk.TclError):
                self._paint(target)

    def _paint(self, colors: tuple[str, ...]) -> None:
        self.delete("all")
        width = max(self.winfo_width(), self._width) if self.winfo_ismapped() else self._width
        fill, outline, foreground = colors
        self._shown = (fill, outline, foreground)
        bg: str | tuple[str, str, str, str] = self.backdrop or self.cget("bg")
        ring: str | None = outline if outline != fill else None
        if self._focused:
            ring = self.theme.c["accent2"]
        self._image = glass_image(
            self, width, self._height, self._radius, fill, bg, ring,
            2.0 if self._focused else 1.0)
        self.create_image(0, 0, image=self._image, anchor="nw")
        nudge = 1 if self._pressed else 0  # pressed content sinks a pixel
        gap = self.theme.px(7)
        words = self._font.measure(self._words) if self._words else 0
        chevron = self.theme.px(12)
        inner = words + (self._glyph + (gap if self._words else 0) if self._lead else 0) + (
            chevron + self.theme.px(4) if self._chevron else 0)
        x = (width - inner) / 2
        mid = self._height / 2 + nudge
        self._glyphs = []
        if self._lead:
            image = icon_image(self, self._lead, self._glyph, foreground, fill,
                               2.0 if self._size == "xl" else 1.8)
            self._glyphs.append(image)
            self.create_image(round(x), round(mid - self._glyph / 2), image=image, anchor="nw")
            x += self._glyph + (gap if self._words else 0)
        if self._words:
            self.create_text(x, mid, text=self._words, fill=foreground, font=self._font,
                             anchor="w")
            x += words
        if self._chevron:
            image = icon_image(self, "chevron-down", chevron,
                               mix_color(foreground, fill, 0.25), fill, 2.0)
            self._glyphs.append(image)
            self.create_image(round(x + self.theme.px(4)), round(mid - chevron / 2 + 1),
                              image=image, anchor="nw")

    def _set_hover(self, value: bool) -> None:
        self._hover = value and self.enabled
        if not value:
            self._pressed = False
        self._draw()

    def _set_pressed(self, value: bool) -> None:
        self._pressed = value and self.enabled
        self._draw()

    def _set_focus(self, value: bool) -> None:
        self._focused = value
        self._shown = None  # the ring appears at once
        self._draw()

    def _key_pressed(self, _event: tk.Event) -> str:
        if self.enabled and self.command is not None:
            self.command()
        return "break"

    def _clicked(self, event: tk.Event) -> None:
        was_pressed = self._pressed
        self._set_pressed(False)
        if not self.enabled or self.command is None or not was_pressed:
            return
        if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow", takefocus=1 if enabled else 0)
        self._shown = None
        self._draw()

    def set_text(self, text: str) -> None:
        self._text = text
        self._parse()
        # Measured afresh each time, so a label that gets shorter gives its width back.
        self._width = self._fixed or self._natural()
        self.configure(width=self._width)
        self._shown = None
        self._draw()


def chip(parent: tk.Misc, theme: Theme, text: str, color: str) -> tk.Canvas:
    """A small status chip: a dot in ``color`` and a word or two in plain text colour, on a
    hairline-bordered surface. The dot carries the colour; the words stay easy to read."""
    c = theme.c
    bg = parent.cget("bg")
    font = theme.font(9)
    height = theme.px(26)
    dot = theme.px(6)
    width = font.measure(text) + dot + theme.px(28)
    canvas = tk.Canvas(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
    canvas.image = glass_image(  # type: ignore[attr-defined]
        canvas, width, height, theme.px(RADIUS["sm"]), c["card"], bg, c["border"])
    canvas.create_image(0, 0, image=canvas.image, anchor="nw")
    x = theme.px(10)
    canvas.create_oval(x, (height - dot) / 2, x + dot, (height + dot) / 2, fill=color, outline="")
    canvas.create_text(x + dot + theme.px(8), height / 2, text=text, fill=c["muted"], font=font,
                       anchor="w")
    return canvas


class Toggle(tk.Canvas):
    """A switch. Click it, or Tab to it and press Space or Enter; the knob slides across."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        value: bool,
        command: Callable[[bool], Any] | None = None,
    ) -> None:
        self.theme = theme
        self.value = value
        self.command = command
        self._tw = theme.px(38)
        self._th = theme.px(22)
        self._ring = theme.px(3)  # room around the track for the focus ring
        self._pos = 1.0 if value else 0.0  # where the knob is, 0 (off) to 1 (on)
        self._focused = False
        self._hover = False
        self._slide_after: str | None = None
        super().__init__(
            parent,
            width=self._tw + 2 * self._ring,
            height=self._th + 2 * self._ring,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self.bind("<ButtonRelease-1>", lambda _e: self.toggle())
        for key in ("<space>", "<Return>", "<KP_Enter>"):
            self.bind(key, lambda _e: (self.toggle(), "break")[1])
        self.bind("<FocusIn>", lambda _e: self._state(focused=True))
        self.bind("<FocusOut>", lambda _e: self._state(focused=False))
        self.bind("<Enter>", lambda _e: self._state(hover=True))
        self.bind("<Leave>", lambda _e: self._state(hover=False))
        self.bind("<Destroy>", lambda _e: self._stop(), add="+")
        self._draw()

    def _state(self, focused: bool | None = None, hover: bool | None = None) -> None:
        if focused is not None:
            self._focused = focused
        if hover is not None:
            self._hover = hover
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        c = self.theme.c
        off = c["border_strong"] if self._hover else c["track"]
        on = c["accent_hover"] if self._hover and self.theme.dark else c["button"]
        track = mix_color(off, on, self._pos)
        margin = self.theme.px(3)
        diameter = self._th - 2 * margin
        x = self._ring + margin + (self._tw - 2 * margin - diameter) * self._pos
        bg = self.cget("bg")
        self._images = [
            glass_image(self, self._tw, self._th, self._th / 2, track, bg),
            glass_image(self, diameter, diameter, diameter / 2, "#FFFFFF", track),
        ]
        if self._focused:
            outer = (self._tw + 2 * self._ring, self._th + 2 * self._ring)
            self._images.append(glass_image(self, outer[0], outer[1], outer[1] / 2, bg, bg,
                                            c["accent2"], 2.0))
            self.create_image(0, 0, image=self._images[-1], anchor="nw")
        self.create_image(self._ring, self._ring, image=self._images[0], anchor="nw")
        self.create_image(round(x), self._ring + margin, image=self._images[1], anchor="nw")

    def _stop(self) -> None:
        if self._slide_after is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._slide_after)
            self._slide_after = None

    def _slide(self) -> None:
        self._slide_after = None
        try:
            goal = 1.0 if self.value else 0.0
            step = 0.26 if goal > self._pos else -0.26
            self._pos = goal if abs(goal - self._pos) <= abs(step) else self._pos + step
            self._draw()
            if self._pos != goal:
                self._slide_after = self.after(18, self._slide)
        except tk.TclError:
            return

    def toggle(self) -> None:
        self.set(not self.value)
        if self.command is not None:
            self.command(self.value)

    def set(self, value: bool) -> None:
        self.value = bool(value)
        self._stop()
        if self.theme.motion and self.winfo_ismapped():
            self._slide()
        else:
            self._pos = 1.0 if self.value else 0.0
            self._draw()


class ProgressBar(tk.Canvas):
    """Thin progress bar. ``live=True`` sends a soft sheen gliding along the filled part,
    so a running transfer looks alive even when the percentage moves slowly."""

    FRAME_MS = 50

    def __init__(self, parent: tk.Misc, theme: Theme, height: int = 6) -> None:
        self.theme = theme
        self.fraction = 0.0
        self.color = theme.c["accent"]
        self.live = False
        self._sheen = 0.0
        self._after: str | None = None
        self._h = theme.px(height)
        super().__init__(parent, height=self._h, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Destroy>", lambda _e: self._stop(), add="+")

    def set(self, fraction: float, color: str | None = None, live: bool = False) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        if color:
            self.color = color
        self.live = live and self.fraction < 1.0
        if self.live and self._after is None:
            self._after = self.after(self.FRAME_MS, self._frame)
        elif not self.live:
            self._stop()
        self._draw()

    def _stop(self) -> None:
        if self._after is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._after)
            self._after = None

    def _frame(self) -> None:
        self._after = None
        try:
            if not self.live or not self.winfo_exists():
                return
            if self.winfo_ismapped() and self.theme.motion:
                self._sheen = (self._sheen + 0.025) % 1.4
                self._draw()
            self._after = self.after(self.FRAME_MS, self._frame)
        except tk.TclError:
            return

    def _draw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 10)
        radius = self._h / 2
        c = self.theme.c
        round_rect(self, 0, 0, width, self._h, radius, fill=c["track"], outline=c["track"])
        filled = width * self.fraction
        if filled >= self._h:
            round_rect(self, 0, 0, filled, self._h, radius, fill=self.color, outline=self.color)
            if self.live:
                # A short bright band that runs left to right inside the filled part.
                band = max(self._h * 3, filled * 0.18)
                x = -band + (filled + band) * min(1.0, self._sheen)
                left, right = max(0.0, x), min(filled, x + band)
                if right - left > 1:
                    light = mix_color(self.theme.c["accent2"], self.color, 0.45)
                    self.create_rectangle(left, 1, right, self._h - 1, fill=light, outline="")
        elif filled > 0:
            self.create_oval(0, 0, self._h, self._h, fill=self.color, outline=self.color)


class Slider(tk.Canvas):
    """Horizontal 0-100 slider in the app's own style (the Tk Scale looks dated)."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        value: int = 50,
        width: int = 240,
        bg: str | None = None,
    ) -> None:
        self.theme = theme
        self.value = max(0, min(100, int(value)))
        self.enabled = True
        self._h = theme.px(22)
        super().__init__(
            parent,
            width=theme.px(width),
            height=self._h,
            bg=bg if bg is not None else parent.cget("bg"),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)

    def set(self, value: int) -> None:
        self.value = max(0, min(100, int(value)))
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def _span(self) -> tuple[float, float]:
        knob = self._h / 2
        return knob, max(self.winfo_width(), self.theme.px(60)) - knob

    def _drag(self, event: tk.Event) -> None:
        if not self.enabled:
            return
        left, right = self._span()
        self.value = round(100 * max(0.0, min(1.0, (event.x - left) / (right - left))))
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        c = self.theme.c
        left, right = self._span()
        mid = self._h / 2
        bar = self.theme.px(6)
        x = left + (right - left) * self.value / 100
        round_rect(
            self, left, mid - bar / 2, right, mid + bar / 2, bar / 2,
            fill=c["track"], outline=c["track"],
        )
        if self.value:
            fill = c["accent"] if self.enabled else c["faint"]
            round_rect(
                self, left, mid - bar / 2, x, mid + bar / 2, bar / 2, fill=fill, outline=fill
            )
        knob = self._h / 2 - 2
        self.create_oval(
            x - knob, mid - knob, x + knob, mid + knob,
            fill=c["card"], outline=c["accent"] if self.enabled else c["border_strong"], width=2,
        )


class Pill(tk.Canvas):
    """Small rounded status label."""

    def __init__(
        self, parent: tk.Misc, theme: Theme, text: str = "", tone: str = "neutral"
    ) -> None:
        self.theme = theme
        self._font = theme.font(8, "bold")
        super().__init__(
            parent, height=theme.px(20), bg=parent.cget("bg"), highlightthickness=0, bd=0
        )
        self.set(text, tone)

    def set(self, text: str, tone: str = "neutral") -> None:
        c = self.theme.c
        fill, fg = {
            "success": (c["success_soft"], c["success"]),
            "warning": (c["warning_soft"], c["warning"]),
            "danger": (c["danger_soft"], c["danger"]),
            "accent": (c["accent_soft"], c["accent"]),
        }.get(tone, (c["neutral_soft"], c["muted"]))
        width = self._font.measure(text) + self.theme.px(16)
        height = self.theme.px(20)
        self.configure(width=width)
        self.delete("all")
        self._image = glass_image(self, width, height, self.theme.px(RADIUS["sm"]), fill,
                                  self.cget("bg"), mix_color(fg, fill, 0.72))
        self.create_image(0, 0, image=self._image, anchor="nw")
        self.create_text(width / 2, height / 2, text=text, fill=fg, font=self._font)


class Avatar(tk.Canvas):
    """A device's badge: a softly tinted rounded square with the platform's icon."""

    def __init__(self, parent: tk.Misc, theme: Theme, platform_name: str, size: int = 40) -> None:
        self.theme = theme
        side = theme.px(size)
        bg = parent.cget("bg")
        super().__init__(parent, width=side, height=side, bg=bg, highlightthickness=0, bd=0)
        key = platform_name.lower()
        color, letter = PLATFORM_STYLE.get(key, (theme.c["faint"], "?"))
        if not theme.dark:
            color = mix_color(color, "#000000", 0.38)
        tint = mix_color(color, theme.c["card"], 0.86)
        self._images = [glass_image(self, side, side, side * 0.28, tint, bg,
                                    mix_color(color, tint, 0.70))]
        self.create_image(0, 0, image=self._images[0], anchor="nw")
        name = PLATFORM_ICON.get(key)
        if name:
            glyph = max(12, int(side * 0.52))
            self._images.append(icon_image(self, name, glyph, color, tint))
            self.create_image((side - glyph) // 2, (side - glyph) // 2, image=self._images[1],
                              anchor="nw")
        else:
            self.create_text(side / 2, side / 2, text=letter, fill=color,
                             font=theme.font(max(9, size // 3), "bold"))


class SignalBars(tk.Canvas):
    """Four rising bars that show link quality from the measured round trip."""

    def __init__(self, parent: tk.Misc, theme: Theme) -> None:
        self.theme = theme
        self._bw = theme.px(4)
        self._gap = theme.px(2)
        self._bh = theme.px(14)
        super().__init__(
            parent,
            width=4 * self._bw + 3 * self._gap,
            height=self._bh,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
        )
        self.set(None)

    def set(self, rtt_ms: float | None) -> None:
        self.delete("all")
        if rtt_ms is None:
            return
        level = 4 if rtt_ms < 15 else 3 if rtt_ms < 40 else 2 if rtt_ms < 100 else 1
        c = self.theme.c
        for index in range(4):
            height = self._bh * (index + 1) / 4
            x1 = index * (self._bw + self._gap)
            color = c["success"] if index < level else c["track"]
            self.create_rectangle(
                x1, self._bh - height, x1 + self._bw, self._bh, fill=color, width=0
            )


class Card(tk.Canvas):
    """Rounded card. Put children into ``card.body``."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        padding: int = 18,
        fill: str | None = None,
        outline: str | None = None,
        radius: int = RADIUS["lg"],
    ) -> None:
        self.theme = theme
        self._image: tk.PhotoImage | None = None
        self._draw_after: str | None = None
        self.fill = fill or theme.c["card"]
        self.outline = outline or theme.c["border"]
        self.radius = theme.px(radius)
        self.padding = theme.px(padding)
        # The body must be (partly) visible inside the canvas, otherwise Tk never
        # maps it and the card would never learn its natural height.
        super().__init__(
            parent,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
            height=2 * self.padding + 4,
        )
        self.body = tk.Frame(self, bg=self.fill)
        self._window = self.create_window(self.padding, self.padding, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._body_resized)
        self.bind("<Configure>", self._resized)

    def _body_resized(self, _event: tk.Event) -> None:
        height = self.body.winfo_reqheight() + 2 * self.padding
        if int(float(self.cget("height"))) != height:
            self.configure(height=height)
        self._schedule_draw()

    def _resized(self, event: tk.Event) -> None:
        self.itemconfigure(self._window, width=max(1, event.width - 2 * self.padding))
        self._schedule_draw()

    def _schedule_draw(self) -> None:
        """Draw at once the first time; while the window is being resized, once it settles."""
        if self._image is None:
            self._draw()
            return
        if self._draw_after is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._draw_after)
        self._draw_after = self.after(40, self._draw)

    def set_colors(self, fill: str | None = None, outline: str | None = None) -> None:
        if fill:
            self.fill = fill
            self.body.configure(bg=fill)
        if outline:
            self.outline = outline
        self._draw()

    def _draw(self) -> None:
        self._draw_after = None
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 4 or height < 4:
            return
        # A glass panel: soft smooth corners, a hairline edge and light along its top rim.
        self._image = glass_image(self, width, height, self.radius, self.fill, self.cget("bg"),
                                  self.outline if self.outline != self.fill else None,
                                  light=0.0)
        self.delete("bg")
        self.create_image(0, 0, image=self._image, anchor="nw", tags=("bg",))
        self.tag_lower("bg")


class ScrollFrame(tk.Frame):
    """Vertically scrolling container; add children to ``.inner``."""

    def __init__(self, parent: tk.Misc, theme: Theme, bg: str | None = None) -> None:
        background = bg or theme.c["bg"]
        super().__init__(parent, bg=background)
        self.theme = theme
        self.canvas = tk.Canvas(
            self,
            bg=background,
            highlightthickness=0,
            bd=0,
            yscrollincrement=theme.px(40),
        )
        self.inner = tk.Frame(self.canvas, bg=background)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width)
        )
        # One global binding; the handler scrolls whichever ScrollFrame is under the
        # pointer, so the wheel also works over child widgets (not only empty gaps).
        self.bind_all("<MouseWheel>", ScrollFrame._on_wheel)
        self.bind_all("<Button-4>", ScrollFrame._on_wheel)
        self.bind_all("<Button-5>", ScrollFrame._on_wheel)

    @staticmethod
    def _under_pointer(event: tk.Event) -> ScrollFrame | None:
        try:
            widget = event.widget.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError, AttributeError):
            return None
        while widget is not None and not isinstance(widget, ScrollFrame):
            widget = widget.master
        return widget

    @staticmethod
    def _on_wheel(event: tk.Event) -> None:
        frame = ScrollFrame._under_pointer(event)
        if frame is None:
            return
        if event.num == 4:
            frame._scroll(-1)
        elif event.num == 5:
            frame._scroll(1)
        elif platform.system() == "Darwin":
            frame._scroll(-event.delta)
        else:
            frame._scroll(-int(event.delta / 120) or (-1 if event.delta > 0 else 1))

    def _scroll(self, units: int) -> None:
        top, bottom = self.canvas.yview()
        if top <= 0 and bottom >= 1:
            return
        self.canvas.yview_scroll(units, "units")


class QrCanvas(tk.Canvas):
    def __init__(self, parent: tk.Misc, theme: Theme, size: int = 240) -> None:
        self.theme = theme
        self._size = theme.px(size)
        super().__init__(
            parent,
            width=self._size,
            height=self._size,
            bg="#FFFFFF",
            highlightthickness=0,
            bd=0,
        )

    def show(self, matrix: list[list[bool]]) -> None:
        self.delete("all")
        self.configure(bg="#FFFFFF")
        modules = len(matrix) + 8
        cell = self._size / modules
        offset = 4 * cell
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    x1 = offset + x * cell
                    y1 = offset + y * cell
                    self.create_rectangle(
                        x1, y1, x1 + cell + 0.6, y1 + cell + 0.6, fill="#111111", width=0
                    )


class Toast:
    """Transient message in the bottom-right corner; it slides in from the right.

    The tone shows twice: a coloured bar and an icon (✓ ! ✕ ●), never colour alone.
    """

    ICONS = {"success": "✓", "warning": "!", "danger": "✕"}
    SLIDE = (64, 34, 16, 6, 2, 0)  # px from the resting spot, one value per frame

    def __init__(self, root: tk.Misc, theme: Theme) -> None:
        self.root = root
        self.theme = theme
        self._frame: tk.Frame | None = None
        self._after: str | None = None
        self._slide_after: str | None = None

    def show(self, text: str, tone: str = "neutral", duration_ms: int = 3500) -> None:
        self.hide()
        c = self.theme.c
        px = self.theme.px
        accent = {
            "success": c["success"],
            "danger": c["danger"],
            "warning": c["warning"],
        }.get(tone, c["accent"])
        frame = tk.Frame(self.root, bg=c["card_hover"], highlightthickness=1,
                         highlightbackground=c["border_strong"])
        tk.Frame(frame, bg=accent, width=px(3)).pack(side="left", fill="y")
        inner = tk.Frame(frame, bg=c["card_hover"], padx=px(12), pady=px(10))
        inner.pack(side="left", fill="both")
        tk.Label(
            inner, text=self.ICONS.get(tone, "●"), fg=accent,
            bg=mix_color(accent, c["card_hover"], 0.84),
            font=self.theme.font(9, "bold"), width=2, pady=px(2),
        ).pack(side="left", padx=(0, px(10)))
        tk.Label(
            inner,
            text=text,
            fg=c["text"],
            bg=c["card_hover"],
            font=self.theme.font(10),
            wraplength=px(380),
            justify="left",
        ).pack(side="left")
        self._frame = frame
        self._slide(frame, 0)
        frame.lift()
        self._after = self.root.after(duration_ms, self.hide)

    def _slide(self, frame: tk.Frame, step: int) -> None:
        self._slide_after = None
        if frame is not self._frame:
            return
        with contextlib.suppress(tk.TclError):
            if not self.theme.motion:
                step = len(self.SLIDE) - 1
            frame.place(relx=1.0, rely=1.0, anchor="se", y=-self.theme.px(44),
                        x=-self.theme.px(20) + self.theme.px(self.SLIDE[step]))
            if step + 1 < len(self.SLIDE):
                self._slide_after = self.root.after(16, lambda: self._slide(frame, step + 1))

    def hide(self) -> None:
        for name in ("_after", "_slide_after"):
            pending = getattr(self, name)
            if pending is not None:
                with contextlib.suppress(tk.TclError):
                    self.root.after_cancel(pending)
                setattr(self, name, None)
        if self._frame is not None:
            with contextlib.suppress(tk.TclError):
                self._frame.destroy()
            self._frame = None


class Modal(tk.Toplevel):
    """Centered, themed dialog window."""

    def __init__(self, parent: tk.Misc, theme: Theme, title: str, width: int = 440) -> None:
        super().__init__(parent)
        self.theme = theme
        self.withdraw()
        self.title(title)
        self.configure(bg=theme.c["bg"], highlightthickness=1,
                       highlightbackground=theme.c["border_strong"],
                       highlightcolor=theme.c["border_strong"])
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.body = tk.Frame(self, bg=theme.c["bg"], padx=theme.px(28), pady=theme.px(24))
        self.body.pack(fill="both", expand=True)
        self._width = theme.px(width)
        tk.Frame(self, bg=theme.c["bg"], width=self._width, height=0).pack()
        self.bind("<Escape>", lambda _e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.on_close: Callable[[], None] | None = None

    def heading(self, title: str, subtitle: str = "") -> None:
        tk.Label(
            self.body,
            text=title,
            bg=self.theme.c["bg"],
            fg=self.theme.c["text"],
            font=self.theme.title_font(15),
            anchor="w",
            justify="left",
        ).pack(fill="x")
        if subtitle:
            tk.Label(
                self.body,
                text=subtitle,
                bg=self.theme.c["bg"],
                fg=self.theme.c["muted"],
                font=self.theme.font(10),
                anchor="w",
                justify="left",
                wraplength=self._width - self.theme.px(56),
            ).pack(fill="x", pady=(self.theme.px(4), 0))

    def present(self) -> None:
        self.update_idletasks()
        parent = self.master.winfo_toplevel()
        width = max(self._width, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - height) // 3
            if not parent.winfo_viewable():
                raise tk.TclError
        except tk.TclError:
            x = (self.winfo_screenwidth() - width) // 2
            y = (self.winfo_screenheight() - height) // 3
        # Only the position is fixed: the dialog keeps sizing itself to its
        # content (rounded cards learn their height once they are mapped).
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        set_dark_titlebar(self, self.theme.dark)
        self.lift()
        self.focus_force()
        with contextlib.suppress(tk.TclError):
            self.grab_set()

    def close(self) -> None:
        if self.on_close is not None:
            callback, self.on_close = self.on_close, None
            callback()
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        with contextlib.suppress(tk.TclError):
            self.destroy()


def entry(parent: tk.Misc, theme: Theme, variable: tk.Variable, **kwargs: Any) -> tk.Entry:
    c = theme.c
    # The flat border is drawn in the field's own colour, so it works as inner padding.
    return tk.Entry(
        parent,
        textvariable=variable,
        bg=c["entry"],
        fg=c["text"],
        insertbackground=c["accent"],
        selectbackground=c["button"],
        selectforeground=c["accent_text"],
        disabledbackground=c["neutral_soft"],
        disabledforeground=c["faint"],
        relief="flat",
        bd=theme.px(6),
        highlightthickness=1,
        highlightbackground=c["border_strong"],
        highlightcolor=c["accent"],
        font=theme.font(10),
        **kwargs,
    )


MONKEY_BROWN = "#8B5A3C"
MONKEY_FACE = "#F2D3B1"
MONKEY_INNER = "#E9B98F"
MONKEY_DARK = "#3B2A20"


def draw_monkey(canvas: tk.Canvas, cx: float, cy: float, size: float, tag: str = "monkey") -> None:
    """Draw the mascot centred on (cx, cy).

    Parts carry extra tags so MonkeyActor can move them: ``<tag>-eye`` (blink),
    ``<tag>-ear``, ``<tag>-mouth`` and ``<tag>-arm`` (hidden until it points).
    """
    s = size / 100.0
    ox, oy = cx - size / 2, cy - size / 2

    def circle(x: float, y: float, r: float, fill: str, extra: tuple[str, ...] = ()) -> None:
        canvas.create_oval(ox + (x - r) * s, oy + (y - r) * s, ox + (x + r) * s, oy + (y + r) * s,
                           fill=fill, outline="", tags=(tag, *extra))

    # The arm comes first so it reaches out from behind the head.
    canvas.create_line(ox + 44 * s, oy + 74 * s, ox + 26 * s, oy + 84 * s, fill=MONKEY_BROWN,
                       width=max(2, 8 * s), capstyle="round", state="hidden",
                       tags=(tag, f"{tag}-arm"))
    circle(26, 84, 5.5, MONKEY_BROWN, (f"{tag}-arm",))
    for item in canvas.find_withtag(f"{tag}-arm"):
        canvas.itemconfigure(item, state="hidden")
    for x in (16, 84):  # ears
        circle(x, 50, 14, MONKEY_BROWN, (f"{tag}-ear",))
        circle(x, 50, 8, MONKEY_INNER, (f"{tag}-ear",))
    circle(50, 50, 33, MONKEY_BROWN)  # head
    canvas.create_line(ox + 44 * s, oy + 19 * s, ox + 50 * s, oy + 11 * s, ox + 55 * s, oy + 18 * s,
                       fill=MONKEY_BROWN, width=max(2, 4 * s), smooth=True, capstyle="round",
                       tags=(tag,))
    circle(39, 45, 12, MONKEY_FACE)  # face lobes
    circle(61, 45, 12, MONKEY_FACE)
    canvas.create_oval(ox + 28 * s, oy + 50 * s, ox + 72 * s, oy + 80 * s, fill=MONKEY_FACE,
                       outline="", tags=(tag,))  # muzzle
    for x in (40, 60):  # eyes
        circle(x, 45, 4.4, MONKEY_DARK, (f"{tag}-eye",))
        circle(x + 1.4, 43.4, 1.4, "#FFFFFF", (f"{tag}-eye",))
    for x in (46, 54):  # nostrils
        circle(x, 60, 1.6, MONKEY_DARK)
    canvas.create_arc(ox + 40 * s, oy + 58 * s, ox + 60 * s, oy + 74 * s, start=200, extent=140,
                      style="arc", outline=MONKEY_DARK, width=max(1.5, 2.6 * s),
                      tags=(tag, f"{tag}-mouth"))


class Monkey(tk.Canvas):
    """A small friendly monkey mascot, drawn with vector shapes (scales cleanly)."""

    BROWN = MONKEY_BROWN
    FACE = MONKEY_FACE
    INNER = MONKEY_INNER
    DARK = MONKEY_DARK

    def __init__(
        self, parent: tk.Misc, theme: Theme, size: int = 64, bg: str | None = None
    ) -> None:
        super().__init__(
            parent, width=size, height=size, bg=bg or theme.c["bg"], highlightthickness=0, bd=0
        )
        draw_monkey(self, size / 2, size / 2, size)


def mix_color(a: str, b: str, amount: float) -> str:
    """Blend hex colour *a* towards *b* (0 → a, 1 → b). Tk has no alpha, so fades blend."""
    amount = max(0.0, min(1.0, amount))
    ra, ga, ba = (int(a[i : i + 2], 16) for i in (1, 3, 5))
    rb, gb, bb = (int(b[i : i + 2], 16) for i in (1, 3, 5))
    red = round(ra + (rb - ra) * amount)
    green = round(ga + (gb - ga) * amount)
    blue = round(ba + (bb - ba) * amount)
    return f"#{red:02x}{green:02x}{blue:02x}"


# ----------------------------------------------------------------- launcher kit
# The Battle.net look: a key-art hero with the monkey as its character, game-icon
# style device tiles, and tooltips for the icon-only buttons.

_HEX = [f"{value:02x}" for value in range(256)]


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def render_backdrop(
    master: tk.Misc, width: int, height: int, c: dict[str, str], step: int = 2
) -> tk.PhotoImage:
    """IDE redesign: a flat page background — no sky, glow, rays or embers. Kept so the
    header/hero code can keep compositing a background image and reading ``color_at``; it
    now simply returns the page colour, so titles sit on clean flat chrome like an editor."""
    image = tk.PhotoImage(master=master, width=max(2, width), height=max(2, height))
    image.put(c["bg"], to=(0, 0, max(2, width), max(2, height)))
    return image


class MonkeyPose:
    """One frame of the walking monkey, in its own 100 × 140 box (feet at y 140)."""

    def __init__(self) -> None:
        self.step = 0.0  # walk phase (radians)
        self.stride = 0.0  # 0 standing … 1 walking
        self.facing = 1  # 1 right, -1 left
        self.bob = 0.0  # + is down
        self.rot = 0.0  # degrees around the belly (the somersault)
        self.crouch = 0.0
        self.grin = 0.0
        self.point = 0.0  # left arm out, down-left at the device tiles
        self.wag = 0.0  # right arm up, finger wagging: "lad være!"
        self.wag_phase = 0.0
        self.blink = False


def monkey_parts(pose: MonkeyPose) -> list[tuple[str, list[float], str, float, str]]:
    """The whole monkey as shapes, back to front: (kind, flat points, colour, line width,
    part). ``kind`` is "poly" (filled) or "line" (round caps, smoothed). Points are in the
    100 × 140 box, already bent by the pose (crouch, somersault, bob)."""
    import math

    brown, face, inner, dark = MONKEY_BROWN, MONKEY_FACE, MONKEY_INNER, MONKEY_DARK
    turn = math.radians(pose.rot)
    cos, sin = math.cos(turn), math.sin(turn)
    squash = 1 - 0.14 * pose.crouch

    def at(x: float, y: float) -> list[float]:
        y = 140 - (140 - y) * squash
        dx, dy = x - 50, y - 92
        return [50 + dx * cos - dy * sin, 92 + dx * sin + dy * cos + pose.bob]

    def oval(x: float, y: float, rx: float, ry: float, n: int = 22) -> list[float]:
        points: list[float] = []
        for i in range(n):
            a = i * math.tau / n
            points += at(x + rx * math.cos(a), y + ry * math.sin(a))
        return points

    def line(*xy: float) -> list[float]:
        points: list[float] = []
        for i in range(0, len(xy), 2):
            points += at(xy[i], xy[i + 1])
        return points

    def lerp(a: tuple[float, float], b: tuple[float, float], k: float) -> tuple[float, float]:
        return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k

    parts: list[tuple[str, list[float], str, float, str]] = []
    side = -pose.facing  # the tail trails behind
    parts.append(("line", line(50 + side * 14, 114, 50 + side * 30, 110, 50 + side * 37, 94,
                               50 + side * 30, 80), brown, 5, "tail"))
    swing = math.sin(pose.step) * pose.stride * 8
    lift = math.sin(pose.step) * pose.stride * 4
    for hip, foot_x, up in ((43, 43 + swing, max(0.0, lift)), (57, 57 - swing, max(0.0, -lift))):
        parts.append(("line", line(hip, 110, foot_x, 133 - up), brown, 9, "leg"))
        parts.append(("poly", oval(foot_x + pose.facing * 2, 136 - up, 7.5, 4.2), inner, 0,
                      "foot"))
    parts.append(("poly", oval(50, 92, 21, 25), brown, 0, "body"))
    parts.append(("poly", oval(50, 97, 13, 17), face, 0, "belly"))
    cheer = pose.grin * 0.7
    left = lerp((27 - swing * 0.6, 104), (20, 62), cheer)
    left = lerp(left, (-8, 120), pose.point)
    right = lerp((73 + swing * 0.6, 104), (80, 62), cheer)
    right = lerp(right, (79, 48), pose.wag)
    for shoulder, hand, part in (((34, 80), left, "arm"), ((66, 80), right, "arm")):
        parts.append(("line", line(*shoulder, *hand), brown, 7, part))
        parts.append(("poly", oval(*hand, 5.2, 5.2), inner, 0, "hand"))
    if pose.wag > 0.2:  # the raised finger, wagging
        tip = (right[0] + math.sin(pose.wag_phase) * 5 * pose.wag, right[1] - 10 * pose.wag)
        parts.append(("line", line(*right, *tip), inner, 3.2, "finger"))
    ears = 1 + 0.35 * pose.grin
    for x in (18, 82):
        parts.append(("poly", oval(x, 40, 12, 12 * ears), brown, 0, "ear"))
        parts.append(("poly", oval(x, 40, 7, 7 * ears), inner, 0, "ear"))
    parts.append(("poly", oval(50, 40, 30, 30, 28), brown, 0, "head"))
    parts.append(("line", line(44, 12, 50, 3, 55, 11), brown, 4, "tuft"))
    parts.append(("poly", oval(40, 36, 11, 11), face, 0, "face"))
    parts.append(("poly", oval(60, 36, 11, 11), face, 0, "face"))
    parts.append(("poly", oval(50, 53, 21, 14, 26), face, 0, "face"))
    look = pose.facing * 1.2
    for x in (40, 60):
        if pose.blink:
            parts.append(("line", line(x - 4, 36, x + 4, 36), dark, 2.2, "eye"))
        else:
            parts.append(("poly", oval(x + look, 36, 4.2, 4.2, 14), dark, 0, "eye"))
            parts.append(("poly", oval(x + look + 1.3, 34.5, 1.3, 1.3, 8), "#FFFFFF", 0, "eye"))
    if pose.wag > 0.3:  # stern brows
        parts.append(("line", line(33, 27, 45, 30), dark, 2.4, "brow"))
        parts.append(("line", line(67, 27, 55, 30), dark, 2.4, "brow"))
    for x in (46, 54):
        parts.append(("poly", oval(x, 50, 1.5, 1.5, 8), dark, 0, "nose"))
    if pose.grin > 0.15:  # open mouth: the lower half of an oval
        tall = 3 + 8 * pose.grin
        points: list[float] = []
        for i in range(13):
            a = i * math.pi / 12
            points += at(50 + 10 * math.cos(a), 56 + tall * math.sin(a))
        parts.append(("poly", points, dark, 0, "mouth"))
    elif pose.wag > 0.3:
        parts.append(("line", line(44, 60, 56, 59), dark, 2.4, "mouth"))
    else:
        smile: list[float] = []
        for i in range(9):
            a = math.radians(200 + 140 * i / 8)  # the lower curve: a smile
            smile += [50 + 9 * math.cos(a), 55 - 6 * math.sin(a)]
        parts.append(("line", line(*smile), dark, 2.4, "mouth"))
    return parts


class MonkeyActor:
    """The whole monkey, alive. Its owner calls tick() every frame (~25 fps).

    It strolls back and forth in its patch (``roam``), stops now and then and points at
    the devices, breathes and blinks. Hops while files move (``set_busy``), happy hops when
    a send lands (``celebrate``), points when a new device turns up (``point``), nods when
    one is ready (``nod``). A click (``tap``) does one of three things, never the same
    twice in a row: a big grin, a stern "Lad være!" with a wagging finger, or a somersault.
    """

    LENGTHS = {"point": 36, "nod": 14, "hops": 26, "grin": 24, "stop": 50, "flip": 30}
    REACTIONS = ("grin", "stop", "flip")
    BUBBLE = "Lad være!"

    def __init__(self, canvas: tk.Canvas, tag: str = "actor", point_left: bool = True,
                 seed: int | None = None) -> None:
        import random

        self.canvas = canvas
        self.tag = tag
        self.point_left = point_left
        self.busy = False
        self.frame = 0
        self.pose = MonkeyPose()
        self._rng = random.Random(seed)
        self._size = 0.0
        self._feet = (0.0, 0.0)
        self._roam = 0.0
        self._x = 0.0  # -1 … 1 across the roam
        self._target = 0.0
        self._rest = 30
        self._gesture: tuple[str, int] | None = None
        self._last_reaction = ""
        self._blink_at = 60

    def place(self, cx: float, feet_y: float, size: float, roam: float = 0.0) -> None:
        """Stand the monkey (``size`` wide, 1.4 × as tall) with its feet on (cx, feet_y),
        free to stroll ``roam`` pixels to either side."""
        self._size, self._feet, self._roam = size, (cx, feet_y), roam
        self._draw()

    @property
    def center(self) -> tuple[float, float]:
        cx, feet = self._feet
        return cx + self._x * self._roam, feet - 0.75 * self._size

    def hit(self, x: float, y: float) -> bool:
        box = self.canvas.bbox(self.tag)
        return bool(box) and box[0] <= x <= box[2] and box[1] <= y <= box[3]

    # ------------------------------------------------------------ gestures
    def set_busy(self, busy: bool) -> None:
        self.busy = busy

    def point(self) -> None:
        self._gesture = ("point", 0)

    def nod(self) -> None:
        self._gesture = ("nod", 0)

    def celebrate(self) -> None:
        self._gesture = ("hops", 0)

    def grin(self) -> None:
        self._react("grin")

    def stop(self) -> None:
        self._react("stop")

    def flip(self) -> None:
        self._react("flip")

    def tap(self) -> str:
        """Clicked: a reaction other than the last one."""
        name = self._rng.choice([r for r in self.REACTIONS if r != self._last_reaction])
        self._react(name)
        return name

    def _react(self, name: str) -> None:
        self._last_reaction = name
        self._gesture = (name, 0)

    @property
    def gesture(self) -> str:
        return self._gesture[0] if self._gesture else ""

    # --------------------------------------------------------------- frame
    def tick(self) -> None:
        import math

        if not self._size:
            return
        self.frame += 1
        t, pose = self.frame, self.pose
        pose.bob = math.sin(t / 14) * 0.8  # breathing
        pose.rot = pose.crouch = pose.grin = pose.point = pose.wag = 0.0
        walking = False
        if self._gesture is not None:
            name, index = self._gesture
            self._play(name, index / (self.LENGTHS[name] - 1))  # ends at rest
            self._gesture = (name, index + 1) if index + 1 < self.LENGTHS[name] else None
        elif self.busy:
            pose.bob -= abs(math.sin(t * math.pi / 13)) * 14
        elif self._roam:
            walking = self._stroll()
        if walking:
            pose.step += 0.38
        pose.stride += ((1.0 if walking else 0.0) - pose.stride) * 0.25
        if t >= self._blink_at:  # eyes shut for three frames now and then
            pose.blink = t - self._blink_at < 3
            if not pose.blink:
                self._blink_at = t + 70 + (t * 37) % 80
        self._draw()

    def _stroll(self) -> bool:
        if self._rest > 0:
            self._rest -= 1
            return False
        gap = self._target - self._x
        if abs(gap) < 0.02:
            self._rest = self._rng.randint(40, 110)
            self._target = self._rng.uniform(-1, 1)
            roll = self._rng.random()
            if roll < 0.3:
                self.point()  # stops and shows you the devices
            elif roll < 0.45:  # now and then a little spontaneous mischief, so it feels alive
                self._react(self._rng.choice(self.REACTIONS))
            return False
        self._x += max(-0.014, min(0.014, gap))
        self.pose.facing = 1 if gap > 0 else -1
        return True

    def _play(self, name: str, p: float) -> None:
        import math

        pose = self.pose
        swell = min(1.0, p / 0.2, (1 - p) / 0.2)  # in, hold, out
        if name == "point":
            pose.point, pose.facing = swell, -1 if self.point_left else 1
        elif name == "nod":
            pose.bob += abs(math.sin(p * math.tau)) * 6
        elif name == "hops":
            pose.bob -= abs(math.sin(p * 3 * math.pi)) * 14 * (1 - p * 0.5)
        elif name == "grin":
            pose.grin = swell
            pose.bob -= math.sin(p * math.pi) * 6
        elif name == "stop":
            pose.wag, pose.wag_phase = swell, p * 40
        elif name == "flip":
            if p < 0.2:
                pose.crouch = p / 0.2
            elif p < 0.85:
                q = (p - 0.2) / 0.65
                pose.bob -= math.sin(q * math.pi) * 32
                pose.rot = -360 * q * pose.facing
            else:
                pose.crouch = (1 - p) / 0.15 * 0.6

    def _draw(self) -> None:
        canvas, tag = self.canvas, self.tag
        canvas.delete(tag)
        s = self._size / 100
        cx, feet = self._feet
        ox, oy = cx + self._x * self._roam - 50 * s, feet - 140 * s
        for kind, points, color, width, part in monkey_parts(self.pose):
            xy = [ox + v * s if i % 2 == 0 else oy + v * s for i, v in enumerate(points)]
            if kind == "poly":
                canvas.create_polygon(xy, fill=color, outline="", tags=(tag, f"{tag}-{part}"))
            else:
                canvas.create_line(xy, fill=color, width=max(1.5, width * s), smooth=True,
                                   capstyle="round", joinstyle="round",
                                   tags=(tag, f"{tag}-{part}"))
        if self.pose.wag > 0.3:
            font = ("Segoe UI", max(8, int(4 + 4 * s)), "bold")
            bx, by = ox + 50 * s, oy - 4 * s
            text = canvas.create_text(bx, by, text=self.BUBBLE, fill=MONKEY_DARK, font=font,
                                      anchor="s", tags=(tag, f"{tag}-bubble"))
            x1, y1, x2, y2 = canvas.bbox(text)
            pad = 5 * s
            box = round_rect(canvas, x1 - pad, y1 - pad, x2 + pad, y2 + pad, 6 * s,
                             fill="#FFFFFF", outline="", tags=(tag, f"{tag}-bubble"))
            canvas.tag_raise(text, box)


class HeroBanner(tk.Canvas):
    """The Send page's header: who you are sending to, in large type, with the main
    actions right under it and the monkey in a small card on the right. The words are
    drawn on the canvas (set_words); the owner packs its buttons into ``buttons``.

    The monkey strolls about; click it and it grins, says "Lad være!" or turns a
    somersault. Animation pauses while the banner is not on screen.
    """

    FRAME_MS = 40

    def __init__(self, parent: tk.Misc, theme: Theme, height: int = 300) -> None:
        self.theme = theme
        self._h = theme.px(height)
        super().__init__(parent, height=self._h, bg=theme.c["bg"], highlightthickness=0, bd=0)
        self.actor = MonkeyActor(self, "hero-monkey", point_left=True)
        self._image: tk.PhotoImage | None = None
        self._size = (0, 0)
        self._resize_after: str | None = None
        self._after: str | None = None
        self._embers: list[list[float]] = []
        self._words = ("", "", "", theme.c["faint"], "")
        self.buttons = tk.Frame(self, bg=theme.c["bg"])
        self._buttons_item = self.create_window(0, 0, window=self.buttons, anchor="nw")
        self.bind("<Configure>", self._configured, add="+")
        self.bind("<Map>", lambda _e: self._start(), add="+")
        self.bind("<Destroy>", lambda _e: self._stop(), add="+")
        # On the canvas, not the tag: the monkey is redrawn every frame.
        self.bind("<Button-1>", lambda e: self.actor.hit(e.x, e.y) and self.actor.tap(), add="+")
        self.bind("<Motion>", lambda e: self.configure(
            cursor="hand2" if self.actor.hit(e.x, e.y) else ""), add="+")

    def color_at(self, x: float, y: float) -> str:
        """The backdrop's colour under (x, y): widgets placed on the art match it."""
        if self._image is None:
            return self.theme.c["hero_top"]
        width, height = self._size
        x = int(max(0, min(width - 1, x)))
        y = int(max(0, min(height - 1, y)))
        red, green, blue = (int(v) for v in self._image.get(x, y))
        return f"#{red:02x}{green:02x}{blue:02x}"

    def _configured(self, event: tk.Event) -> None:
        if (event.width, event.height) == self._size:
            return
        if self._resize_after is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._resize_after)
        # First paint at once; while the window is being dragged wider, wait for it to settle.
        delay = 1 if self._image is None else 180
        self._resize_after = self.after(delay, self._render)

    def _render(self) -> None:
        self._resize_after = None
        width, height = self.winfo_width(), self.winfo_height()
        if width < 40 or height < 40:
            return
        self._size = (width, height)
        c, px = self.theme.c, self.theme.px
        self._image = render_backdrop(self, width, height, c, 1)  # flat page colour
        self.delete("backdrop")
        self.create_image(0, 0, image=self._image, anchor="nw", tags=("backdrop",))
        self.tag_lower("backdrop")
        # A small mascot card on the right holds the monkey, level with the words.
        card = int(min(height - px(36), px(136)))
        self._card = card
        cx2 = width
        cx1, cy1 = cx2 - card, px(18)
        cy2 = cy1 + card
        self._card_image = glass_image(self, card, card, px(RADIUS["lg"]), c["card"], c["bg"],
                                       c["border"])
        self.create_image(cx1, cy1, image=self._card_image, anchor="nw", tags=("backdrop",))
        self.actor.place((cx1 + cx2) / 2, cy2 - px(16), card * 0.60, roam=card * 0.10)
        self._layout_words()

    def set_words(
        self, eyebrow: str, title: str, status: str = "", dot: str | None = None, hint: str = ""
    ) -> None:
        """Monospace eyebrow (small, accent), a clean bold title, a status line with a
        coloured dot, and a hint under the buttons. IDE look: no uppercasing, no key art."""
        words = (eyebrow, title, status, dot or self.theme.c["faint"], hint)
        if words != self._words:
            self._words = words
            self._layout_words()

    def _layout_words(self) -> None:
        c, px = self.theme.c, self.theme.px
        width, height = self._size
        if not width:
            return
        self.delete("words")
        eyebrow, title, status, dot, hint = self._words
        x = px(1)
        room = max(px(240), width - getattr(self, "_card", px(136)) - px(32))
        title_size = 24 if len(title) <= 18 else 20 if len(title) <= 26 else 17
        fonts = (self.theme.font(8, "bold", self.theme.mono),
                 self.theme.title_font(title_size), self.theme.font(10))
        y = px(20)
        self.create_text(x, y, text=eyebrow.upper(), fill=c["accent"], font=fonts[0], anchor="nw",
                         tags=("words",))
        y += fonts[0].metrics("linespace") + px(6)
        self.create_text(x, y, text=title, fill=c["text"], font=fonts[1], anchor="nw",
                         width=room, tags=("words",))
        y += fonts[1].metrics("linespace") * (1 if fonts[1].measure(title) < room
                                               else 2) + px(4)
        if status:
            r = px(4)
            mid = y + fonts[2].metrics("linespace") / 2
            self.create_oval(x, mid - r, x + 2 * r, mid + r, fill=dot, outline="",
                             tags=("words",))
            self.create_text(x + 2 * r + px(8), y, text=status, fill=c["muted"], font=fonts[2],
                             anchor="nw", tags=("words",))
            y += fonts[2].metrics("linespace")
        y += px(16)
        self.coords(self._buttons_item, 0, y)
        self.refresh_buttons()
        if hint:
            y += max(self.buttons.winfo_reqheight(), px(44)) + px(12)
            self.create_text(x, y, text=hint, fill=c["faint"], font=self.theme.font(9),
                             anchor="nw", width=room, tags=("words",))

    def refresh_buttons(self) -> None:
        """The buttons take the art's colour behind each of them (Tk widgets are opaque, and
        it shows in their round corners)."""
        x, y = self.coords(self._buttons_item)
        mid = y + self.theme.px(24)
        fallback = self.color_at(x + self.theme.px(100), mid)
        with contextlib.suppress(tk.TclError):
            self.buttons.configure(bg=fallback)
        # No update_idletasks() here to place them first: on macOS that re-entered layout
        # without end. A button not placed yet takes the fallback; the next refresh fixes it.
        for widget in self.buttons.winfo_children():
            with contextlib.suppress(tk.TclError):
                if widget.winfo_width() <= 1:
                    widget.configure(bg=fallback)
                    continue
                left, top = x + widget.winfo_x(), y + widget.winfo_y()
                right, bottom = left + widget.winfo_width() - 1, top + widget.winfo_height() - 1
                widget.configure(bg=self.color_at((left + right) / 2, (top + bottom) / 2))
                if isinstance(widget, Button):
                    backdrop = (self.color_at(left, top), self.color_at(right, top),
                                self.color_at(left, bottom), self.color_at(right, bottom))
                    if backdrop != widget.backdrop:
                        widget.backdrop = backdrop
                        widget._draw()

    def _spawn_embers(self, width: int, height: int) -> None:
        import random

        self.delete("ember")
        rng = random.Random(7)
        self._embers = []
        for _ in range(34):
            x, y = rng.uniform(width * 0.35, width), rng.uniform(0, height)
            r = rng.choice((1.0, 1.4, 1.8, 2.4)) * self.theme.scale
            item = self.create_oval(x - r, y - r, x + r, y + r, outline="", tags=("ember",))
            # x, y, radius, rise speed, sway phase, twinkle phase, item
            self._embers.append([x, y, r, rng.uniform(0.25, 0.9), rng.uniform(0, 6.3),
                                 rng.uniform(0, 6.3), item])
        self.tag_raise("hero-monkey")

    def burst(self) -> None:
        """A ring of sparks flies out from the monkey (a send has landed)."""
        import math

        width, height = self._size
        if not width:
            return
        cx, cy = self.actor.center
        self._sparks = []
        for index in range(18):
            angle = index * math.tau / 18
            item = self.create_oval(cx, cy, cx, cy, outline="", fill=self.theme.c["accent2"],
                                    tags=("spark",))
            self._sparks.append([cx, cy, math.cos(angle), math.sin(angle), item])
        self._spark_frame = 0

    def _animate_sparks(self) -> None:
        sparks = getattr(self, "_sparks", None)
        if not sparks:
            return
        self._spark_frame += 1
        step = self._spark_frame
        if step > 22:
            self.delete("spark")
            self._sparks = []
            return
        fade = step / 22
        r = 3.2 * self.theme.scale * (1 - fade * 0.6)
        speed = 6.5 * self.theme.scale * (1 - fade)
        for spark in sparks:
            spark[0] += spark[2] * speed
            spark[1] += spark[3] * speed
            x, y = spark[0], spark[1]
            self.coords(spark[4], x - r, y - r, x + r, y + r)
            self.itemconfigure(spark[4], fill=mix_color("#FFFFFF", self.color_at(x, y),
                                                        0.15 + fade * 0.85))

    def _start(self) -> None:
        if self._after is None:
            self._after = self.after(self.FRAME_MS, self._frame)

    def _stop(self) -> None:
        if self._after is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._after)
            self._after = None

    def _frame(self) -> None:
        self._after = None
        try:
            if not self.winfo_exists():
                return
            if self.winfo_ismapped() and self._image is not None:
                self._animate()
                self._animate_sparks()
        except tk.TclError:
            return
        self._after = self.after(self.FRAME_MS, self._frame)

    def _animate(self) -> None:
        import math

        width, height = self._size
        t = self.actor.frame
        recolor = t % 3 == 0
        light = self.theme.c["accent2"]
        for ember in self._embers:
            x, y, r, speed, sway, twinkle, item = ember
            y -= speed
            x += math.sin(t / 30 + sway) * 0.35
            if y < -r:
                y, x = height + r, (x - width * 0.35 + 97) % (width * 0.65) + width * 0.35
            ember[0], ember[1] = x, y
            self.coords(item, x - r, y - r, x + r, y + r)
            if recolor:
                # Brightest mid-height, fading out towards the top and the page below.
                glow = 0.25 + 0.45 * (0.5 + 0.5 * math.sin(t / 9 + twinkle))
                glow *= max(0.0, min(1.0, 1.4 - abs(y / height - 0.45) * 2.2))
                self.itemconfigure(item, fill=mix_color(light, self.color_at(x, y), 1 - glow))
        self.actor.tick()


class DeviceTiles(tk.Frame):
    """Your devices as a row of compact cards: the platform's icon, the name and a short
    status line. The cards wrap onto more rows when the window is narrow.

    The selected card is tinted blue; a pointer over a card lifts its surface. ``nodes``
    are dicts with id, name, platform, online, selected and sub (a short status line);
    ``on_add`` adds a dashed "Forbind ny" card at the end.
    """

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        on_pick: Callable[[str], None],
        on_add: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=theme.c["bg"])
        self.theme = theme
        self.on_pick = on_pick
        self.on_add = on_add
        self.nodes: list[dict[str, Any]] = []
        self.tiles: dict[str, tk.Canvas] = {}
        self._order: list[tk.Canvas] = []
        self._tw, self._th = theme.px(190), theme.px(60)
        self._gap = theme.px(10)
        self._cols = 0
        self._phase = 0.0
        self._pulse_after: str | None = None
        self.bind("<Configure>", lambda e: self._reflow(e.width), add="+")
        self.set_nodes([])

    def set_nodes(self, nodes: list[dict[str, Any]]) -> None:
        if nodes == self.nodes and self.tiles:
            return
        self.nodes = [dict(node) for node in nodes]
        for tile in self.winfo_children():
            tile.destroy()
        self.tiles = {}
        self._order = []
        for node in self.nodes:
            self.tiles[node["id"]] = self._tile(node)
        if self.on_add is not None:
            self._tile({"id": "+", "name": "Forbind ny", "sub": "QR · IP · Bluetooth"})
        self._cols = 0
        self._reflow(self.winfo_width())
        if self._pulse_after is None and any(node.get("sending") for node in self.nodes):
            self._pulse_after = self.after(60, self._pulse)

    def _reflow(self, width: int) -> None:
        """As many cards per row as fit; the rest wrap."""
        if width <= 1:  # not on screen yet: a sensible first guess
            width = 4 * (self._tw + self._gap)
        cols = max(1, (width + self._gap) // (self._tw + self._gap))
        if cols == self._cols:
            return
        self._cols = cols
        for index, tile in enumerate(self._order):
            tile.grid(row=index // cols, column=index % cols, sticky="w",
                      padx=(0, self._gap), pady=(0, self._gap))

    def _pulse(self) -> None:
        """The card being sent to breathes cyan until the send is over."""
        self._pulse_after = None
        try:
            if not self.winfo_exists() or not any(n.get("sending") for n in self.nodes):
                return
            self._phase += 0.14
            for tile in self.tiles.values():
                if tile.node.get("sending") and tile.winfo_ismapped():  # type: ignore[attr-defined]
                    self._paint(tile)
            self._pulse_after = self.after(60, self._pulse)
        except tk.TclError:
            return

    def _tile(self, node: dict[str, Any]) -> tk.Canvas:
        tile = tk.Canvas(self, width=self._tw, height=self._th, bg=self.theme.c["bg"],
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self._order.append(tile)
        tile.node = node  # type: ignore[attr-defined]
        tile.hover = False  # type: ignore[attr-defined]
        tile.focused = False  # type: ignore[attr-defined]
        self._paint(tile)
        key = node["id"]
        action = (lambda: self.on_add and self.on_add()) if key == "+" else (
            lambda: self.on_pick(key))
        tile.bind("<ButtonRelease-1>", lambda _e: action())
        for name in ("<Return>", "<space>"):
            tile.bind(name, lambda _e: (action(), "break")[1])
        tile.bind("<Enter>", lambda _e: self._hover(tile, True))
        tile.bind("<Leave>", lambda _e: self._hover(tile, False))
        tile.bind("<FocusIn>", lambda _e: self._focus(tile, True))
        tile.bind("<FocusOut>", lambda _e: self._focus(tile, False))
        return tile

    def _hover(self, tile: tk.Canvas, value: bool) -> None:
        tile.hover = value  # type: ignore[attr-defined]
        self._paint(tile)

    def _focus(self, tile: tk.Canvas, value: bool) -> None:
        tile.focused = value  # type: ignore[attr-defined]
        self._paint(tile)

    def _fit(self, text: str, font: tkfont.Font, room: int) -> str:
        if font.measure(text) <= room:
            return text
        while len(text) > 1 and font.measure(text + "…") > room:
            text = text[:-1]
        return text.rstrip() + "…"

    def _paint(self, tile: tk.Canvas) -> None:
        c, px = self.theme.c, self.theme.px
        node = tile.node  # type: ignore[attr-defined]
        hover = tile.hover  # type: ignore[attr-defined]
        w, h = self._tw, self._th
        tile.delete("all")
        selected = bool(node.get("selected"))
        adding = node["id"] == "+"
        online = bool(node.get("online")) or adding
        fill = (mix_color(c["accent_soft"], c["accent"], 0.10 if hover else 0.0) if selected
                else c["card_hover"] if hover else c["bg"] if adding else c["card"])
        outline = c["accent"] if selected else c["border_strong"] if hover else c["border"]
        if node.get("sending"):
            import math

            # In six steps, so the breathing edge reuses its few cached images.
            level = round((0.5 - 0.5 * math.sin(self._phase)) * 6) / 6
            outline = mix_color(c["accent2"], c["border"], level)
        if tile.focused:  # type: ignore[attr-defined]
            outline = c["accent2"]
        heavy = selected or node.get("sending") or tile.focused  # type: ignore[attr-defined]
        radius = px(10)
        images = [glass_image(tile, w, h, radius, fill, c["bg"],
                              None if adding and not hover and not tile.focused  # type: ignore[attr-defined]
                              else outline, 1.5 if heavy else 1.0)]
        tile.create_image(0, 0, image=images[0], anchor="nw")
        if adding and not hover and not tile.focused:  # type: ignore[attr-defined]
            round_rect(tile, 1, 1, w - 2, h - 2, radius, fill="", outline=c["border_strong"],
                       dash=(3, 4))
        side = px(34)
        ax, ay = px(12), (h - side) // 2
        if adding:
            color = c["accent"] if hover else c["muted"]
            tint = c["neutral_soft"] if hover else c["card"]
            icon = "plus"
        else:
            color, _letter = PLATFORM_STYLE.get(str(node.get("platform", "")).lower(),
                                                (c["faint"], "?"))
            if not self.theme.dark:
                color = mix_color(color, "#000000", 0.38)
            if not online:
                color = mix_color(color, fill, 0.5)
            tint = mix_color(color, fill, 0.86)
            icon = PLATFORM_ICON.get(str(node.get("platform", "")).lower(), "monitor")
        images.append(glass_image(tile, side, side, px(9), tint, fill,
                                  mix_color(color, tint, 0.72)))
        tile.create_image(ax, ay, image=images[-1], anchor="nw")
        glyph = px(18)
        images.append(icon_image(tile, icon, glyph, color, tint))
        tile.create_image(ax + (side - glyph) // 2, ay + (side - glyph) // 2, image=images[-1],
                          anchor="nw")
        if not adding:
            r = px(4)
            dx, dy = ax + side - px(2), ay + side - px(2)
            tile.create_oval(dx - r, dy - r, dx + r, dy + r,
                             fill=c["success"] if online else c["faint"], outline=fill, width=2)
        tile.images = images  # type: ignore[attr-defined]
        tx = ax + side + px(11)
        room = w - tx - px(10)
        name_font, sub_font = self.theme.font(10, "bold"), self.theme.font(9)
        tile.create_text(tx, h / 2 - px(9), text=self._fit(node["name"], name_font, room),
                         anchor="w", fill=c["text"] if online else c["muted"], font=name_font)
        tile.create_text(tx, h / 2 + px(10), text=self._fit(node.get("sub", ""), sub_font, room),
                         anchor="w", fill=c["accent"] if selected else c["faint"], font=sub_font)


class NavRow(tk.Canvas):
    """One entry of the side menu: a drawn icon, the page's name and a small counter.

    The open page gets a raised surface and a blue marker on its edge; a pointer over a row
    lifts it slightly. Tab reaches the rows and Enter or Space opens the focused one.
    ``set_compact(True)`` shows the icon alone (the narrow menu of a small window).
    """

    def __init__(self, parent: tk.Misc, theme: Theme, icon: str, label: str,
                 command: Callable[[], Any]) -> None:
        self.theme = theme
        self.icon = icon
        self.label = label
        self.command = command
        self.badge = ""
        self.active = False
        self.compact = False
        self._hover = False
        self._focused = False
        self._height = theme.px(32)
        super().__init__(parent, height=self._height, width=theme.px(40), bg=parent.cget("bg"),
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", lambda _e: self._set(hover=True))
        self.bind("<Leave>", lambda _e: self._set(hover=False))
        self.bind("<FocusIn>", lambda _e: self._set(focused=True))
        self.bind("<FocusOut>", lambda _e: self._set(focused=False))
        self.bind("<Button-1>", lambda _e: self.command())
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, lambda _e: (self.command(), "break")[1])

    def _set(self, hover: bool | None = None, focused: bool | None = None) -> None:
        if hover is not None:
            self._hover = hover
        if focused is not None:
            self._focused = focused
        self._draw()

    def set_active(self, active: bool) -> None:
        if active != self.active:
            self.active = active
            self._draw()

    def set_badge(self, text: str) -> None:
        if text != self.badge:
            self.badge = text
            self._draw()

    def set_compact(self, compact: bool) -> None:
        if compact != self.compact:
            self.compact = compact
            self._draw()

    def _draw(self) -> None:
        c, px = self.theme.c, self.theme.px
        self.delete("all")
        width, height = max(self.winfo_width(), px(40)), self._height
        bg = self.cget("bg")
        fill = c["nav_active"] if self.active else c["nav_hover"] if self._hover else bg
        ring = c["accent2"] if self._focused else (c["border"] if self.active else None)
        self._images = [glass_image(self, width, height, px(7), fill, bg, ring,
                                    2.0 if self._focused else 1.0)]
        self.create_image(0, 0, image=self._images[0], anchor="nw")
        lit = self.active or self._hover
        glyph = px(16)
        color = c["accent"] if self.active else c["text"] if self._hover else c["muted"]
        self._images.append(icon_image(self, self.icon, glyph, color, fill))
        x = (width - glyph) // 2 if self.compact else px(11)
        self.create_image(x, (height - glyph) // 2, image=self._images[1], anchor="nw")
        if self.active:
            self.create_line(px(1), height * 0.28, px(1), height * 0.72, fill=c["accent"],
                             width=px(3), capstyle="round")
        if self.compact:
            if self.badge:  # a dot in the corner says "something new here"
                r = px(3)
                self.create_oval(width - px(12) - r, px(8) - r, width - px(12) + r, px(8) + r,
                                 fill=c["accent"], outline=fill)
            return
        self.create_text(px(37), height / 2, text=self.label, anchor="w",
                         fill=c["text"] if lit else c["muted"],
                         font=self.theme.font(10, "bold" if self.active else "normal"))
        if self.badge:
            font = self.theme.font(8, "bold")
            bw, bh = max(px(20), font.measure(self.badge) + px(12)), px(18)
            self._images.append(glass_image(self, bw, bh, bh / 2, c["accent_soft"], fill,
                                            mix_color(c["accent"], c["accent_soft"], 0.6)))
            bx = width - bw - px(8)
            self.create_image(bx, (height - bh) // 2, image=self._images[-1], anchor="nw")
            self.create_text(bx + bw / 2, height / 2, text=self.badge, fill=c["accent"],
                             font=font)


class NavBadge:
    """The counter on a menu row, with the ``configure(text=…)`` / ``cget("text")`` of the
    label it used to be, so the pages that set it need not know how it is drawn."""

    def __init__(self, row: NavRow) -> None:
        self._row = row

    def configure(self, **options: Any) -> None:
        if "text" in options:
            self._row.set_badge(str(options["text"]))

    config = configure

    def cget(self, key: str) -> str:
        return self._row.badge if key == "text" else ""


def key_cap(parent: tk.Misc, theme: Theme, text: str) -> tk.Label:
    """A small keyboard key ("Ctrl", "K") for showing a shortcut."""
    c = theme.c
    return tk.Label(parent, text=text, bg=c["neutral_soft"], fg=c["muted"],
                    font=theme.font(8, family=theme.mono), padx=theme.px(5), pady=theme.px(1),
                    highlightthickness=1, highlightbackground=c["border_strong"])


class CommandPalette:
    """Ctrl+K: a search box over the window. Type a few letters of a page or an action,
    choose with the arrow keys and press Enter. Escape, or a click elsewhere, closes it.

    ``items`` are (title, group, shortcut, action) tuples.
    """

    ROWS = 8

    def __init__(self, root: tk.Misc, theme: Theme) -> None:
        self.root = root
        self.theme = theme
        self.frame: tk.Frame | None = None
        self.entry: tk.Entry | None = None
        self.query = tk.StringVar(master=root)
        self.items: list[tuple[str, str, str, Callable[[], Any]]] = []
        self.matches: list[tuple[str, str, str, Callable[[], Any]]] = []
        self.index = 0
        self._list: tk.Frame | None = None
        self._images: list[tk.PhotoImage] = []
        self.query.trace_add("write", lambda *_a: self._filter())
        root.bind_all("<Button-1>", self._clicked_elsewhere, add="+")

    @property
    def is_open(self) -> bool:
        return self.frame is not None

    def toggle(self, items: list[tuple[str, str, str, Callable[[], Any]]]) -> None:
        if self.is_open:
            self.close()
        else:
            self.open(items)

    def open(self, items: list[tuple[str, str, str, Callable[[], Any]]]) -> None:
        self.close()
        c, px = self.theme.c, self.theme.px
        self.items = list(items)
        surface = c["card"]
        frame = tk.Frame(self.root, bg=surface, highlightthickness=1,
                         highlightbackground=c["border_strong"])
        self.frame = frame
        top = tk.Frame(frame, bg=surface)
        top.pack(fill="x", padx=px(14), pady=(px(12), px(10)))
        self._images = [icon_image(frame, "search", px(18), c["faint"], surface)]
        tk.Label(top, image=self._images[0], bg=surface).pack(side="left", padx=(0, px(10)))
        self.query.set("")
        self.entry = tk.Entry(top, textvariable=self.query, bg=surface, fg=c["text"],
                              insertbackground=c["accent"], relief="flat", bd=0,
                              highlightthickness=0, font=self.theme.font(12))
        self.entry.pack(side="left", fill="x", expand=True)
        key_cap(top, self.theme, "Esc").pack(side="right")
        tk.Frame(frame, bg=c["border"], height=1).pack(fill="x")
        self._list = tk.Frame(frame, bg=surface)
        self._list.pack(fill="x", padx=px(6), pady=px(6))
        tk.Frame(frame, bg=c["border"], height=1).pack(fill="x")
        foot = tk.Frame(frame, bg=surface)
        foot.pack(fill="x", padx=px(14), pady=px(7))
        for keys, words in ((("↑", "↓"), "vælg"), (("Enter",), "kør"), (("Esc",), "luk")):
            for key in keys:
                key_cap(foot, self.theme, key).pack(side="left", padx=(0, px(4)))
            tk.Label(foot, text=words, bg=surface, fg=c["faint"],
                     font=self.theme.font(8)).pack(side="left", padx=(px(2), px(14)))
        self.entry.bind("<Escape>", lambda _e: (self.close(), "break")[1])
        self.entry.bind("<Return>", lambda _e: (self.run(), "break")[1])
        self.entry.bind("<KP_Enter>", lambda _e: (self.run(), "break")[1])
        self.entry.bind("<Down>", lambda _e: (self.move(1), "break")[1])
        self.entry.bind("<Up>", lambda _e: (self.move(-1), "break")[1])
        self.entry.bind("<Next>", lambda _e: (self.move(self.ROWS), "break")[1])
        self.entry.bind("<Prior>", lambda _e: (self.move(-self.ROWS), "break")[1])
        width = min(px(580), max(px(320), self.root.winfo_width() - px(48)))
        frame.place(relx=0.5, y=px(64), anchor="n", width=width)
        frame.lift()
        self._filter()
        self.entry.focus_set()

    def close(self) -> None:
        frame, self.frame, self.entry, self._list = self.frame, None, None, None
        if frame is not None:
            with contextlib.suppress(tk.TclError):
                frame.destroy()

    def _clicked_elsewhere(self, event: tk.Event) -> None:
        if self.frame is None:
            return
        widget = event.widget
        while widget is not None and not isinstance(widget, str):
            if widget is self.frame:
                return
            widget = getattr(widget, "master", None)
        self.close()

    def _filter(self) -> None:
        if self.frame is None:
            return
        words = self.query.get().lower().split()
        self.matches = [item for item in self.items
                        if all(word in f"{item[0]} {item[1]}".lower() for word in words)]
        # Best first: a title that starts with what was typed, then a word that does.
        if words:
            def rank(item: tuple[str, str, str, Callable[[], Any]]) -> int:
                title = item[0].lower()
                if title.startswith(words[0]):
                    return 0
                return 1 if any(part.startswith(words[0]) for part in title.split()) else 2

            self.matches.sort(key=rank)
        self.index = 0
        self._render()

    def move(self, step: int) -> None:
        if self.matches:
            self.index = max(0, min(len(self.matches) - 1, self.index + step))
            self._render()

    def run(self, index: int | None = None) -> None:
        if index is not None:
            self.index = index
        if not 0 <= self.index < len(self.matches):
            return
        action = self.matches[self.index][3]
        self.close()
        action()

    def _render(self) -> None:
        box = self._list
        if box is None:
            return
        c, px = self.theme.c, self.theme.px
        surface = c["card"]
        for child in box.winfo_children():
            child.destroy()
        if not self.matches:
            tk.Label(box, text=f"Intet fundet for “{self.query.get().strip()}”", bg=surface,
                     fg=c["muted"], font=self.theme.font(10), pady=px(14)).pack(fill="x")
            return
        first = max(0, min(self.index - self.ROWS + 1, len(self.matches) - self.ROWS))
        first = max(first, 0)
        if self.index < first:
            first = self.index
        for position in range(first, min(len(self.matches), first + self.ROWS)):
            title, group, shortcut, _action = self.matches[position]
            chosen = position == self.index
            bg = c["nav_active"] if chosen else surface
            row = tk.Frame(box, bg=bg, cursor="hand2")
            row.pack(fill="x")
            tk.Frame(row, bg=c["accent"] if chosen else bg, width=px(3)).pack(
                side="left", fill="y")
            parts: list[tk.Misc] = [row]
            parts.append(tk.Label(row, text=title, bg=bg, fg=c["text"], anchor="w",
                                  font=self.theme.font(10, "bold" if chosen else "normal"),
                                  padx=px(9), pady=px(7)))
            parts[-1].pack(side="left")
            for key in reversed(shortcut.split("+") if shortcut else []):
                cap = key_cap(row, self.theme, key)
                cap.pack(side="right", padx=(0, px(6)))
                parts.append(cap)
            parts.append(tk.Label(row, text=group, bg=bg, fg=c["faint"], anchor="e",
                                  font=self.theme.font(9), padx=px(8)))
            parts[-1].pack(side="right")
            for part in parts:
                part.bind("<Button-1>", lambda _e, i=position: self.run(i))


class PopupMenu(tk.Menu):
    """A drop-down or right-click menu drawn in the app's own look.

    It is filled like a ``tk.Menu`` (``add_command`` with ``label``, ``command`` and, when
    there is one, ``accelerator="Ctrl+O"``; ``add_separator``), but ``tk_popup`` shows a
    themed panel inside the window instead of the system menu: a hover row, key caps for
    shortcuts, a drawn tick for a label that starts with "✓", and the entry's own
    ``foreground`` for a destructive action. Arrow keys move, Enter or Space runs,
    Escape or a click elsewhere closes.
    """

    _open: PopupMenu | None = None  # only one menu is open at a time
    # The button whose press just closed its own menu, and when: the release that follows
    # must not open the menu again (a second click on "▾" closes it, like any menu button).
    _dismissed: tuple[tk.Misc | None, float] = (None, 0.0)

    def __init__(self, master: tk.Misc, theme: Theme) -> None:
        super().__init__(master, tearoff=0)
        self.theme = theme
        self.panel: tk.Frame | None = None
        self.active: int | None = None
        self._rows: dict[int, list[tk.Misc]] = {}
        self._images: list[tk.PhotoImage] = []
        self._focus_before: tk.Misc | None = None
        self._slide_after: str | None = None
        self._anchor: tk.Misc | None = None

    @property
    def is_open(self) -> bool:
        return self.panel is not None

    def commands(self) -> list[int]:
        """The indexes of the entries that can be chosen right now."""
        last = self.index("end")
        return [index for index in range(0 if last is None else last + 1)
                if self.type(index) == "command"
                and str(self.entrycget(index, "state")) != "disabled"]

    def popup_below(self, widget: tk.Misc) -> None:
        closed_by, when = PopupMenu._dismissed
        PopupMenu._dismissed = (None, 0.0)
        if closed_by is widget and time.monotonic() - when < 0.6:
            return
        self._anchor = widget
        self.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())

    def tk_popup(self, x: int, y: int, entry: str | int = "") -> None:
        if PopupMenu._open is not None:
            PopupMenu._open.close()
        last = self.index("end")
        if last is None:
            return
        theme = self.theme
        c, px = theme.c, theme.px
        under = None
        with contextlib.suppress(KeyError, tk.TclError):
            under = self.winfo_containing(x, y)
        top = (under or self.master).winfo_toplevel()
        surface = c["card_hover"]
        panel = tk.Frame(top, bg=surface, highlightthickness=1,
                         highlightbackground=c["border_strong"], takefocus=1)
        inner = tk.Frame(panel, bg=surface)
        inner.pack(fill="both", expand=True, padx=px(4), pady=px(4))
        labels = [str(self.entrycget(index, "label")) for index in range(last + 1)
                  if self.type(index) == "command"]
        ticks = any(label.startswith(("✓", "   ")) for label in labels)
        self._rows, self._images = {}, []
        tick_size = px(14)
        for index in range(last + 1):
            if self.type(index) == "separator":
                tk.Frame(inner, bg=c["border_strong"], height=1).pack(
                    fill="x", padx=px(6), pady=px(4))
                continue
            if self.type(index) != "command":
                continue
            label = str(self.entrycget(index, "label"))
            ticked = label.startswith("✓")
            text = label.lstrip("✓").strip()
            disabled = str(self.entrycget(index, "state")) == "disabled"
            own = str(self.entrycget(index, "foreground"))
            ink = c["faint"] if disabled else (own if own.startswith("#") else c["text"])
            row = tk.Frame(inner, bg=surface, cursor="arrow" if disabled else "hand2")
            row.pack(fill="x")
            parts: list[tk.Misc] = [row]
            if ticks:
                mark = tk.Label(row, bg=surface, width=tick_size, height=tick_size)
                if ticked:
                    self._images.append(
                        icon_image(row, "check", tick_size, c["accent"], surface, 2.0))
                    self._images.append(
                        icon_image(row, "check", tick_size, c["accent"], c["nav_active"], 2.0))
                    mark.configure(image=self._images[-2])
                    mark.pair = (self._images[-2], self._images[-1])  # type: ignore[attr-defined]
                else:
                    blank = tk.PhotoImage(master=row, width=tick_size, height=tick_size)
                    self._images.append(blank)
                    mark.configure(image=blank)
                mark.pack(side="left", padx=(px(8), 0))
                parts.append(mark)
            name = tk.Label(row, text=text, bg=surface, fg=ink, anchor="w",
                            font=theme.font(10), padx=px(10), pady=px(6))
            name.pack(side="left")
            parts.append(name)
            keys = str(self.entrycget(index, "accelerator"))
            caps = tk.Frame(row, bg=surface)
            caps.pack(side="right", padx=(px(24), px(8)))
            parts.append(caps)
            for key in keys.split("+") if keys else []:
                cap = key_cap(caps, theme, key)
                cap.pack(side="left", padx=(px(4), 0))
                parts.append(cap)
            self._rows[index] = parts
            if disabled:
                continue
            for part in parts:
                part.bind("<Enter>", lambda _e, i=index: self._set_active(i), add="+")
                part.bind("<ButtonRelease-1>", lambda _e, i=index: self.choose(i))
        self.panel = panel
        self.active = None
        PopupMenu._open = self
        panel.bind("<Escape>", lambda _e: (self.close(), "break")[1])
        panel.bind("<Down>", lambda _e: (self.move(1), "break")[1])
        panel.bind("<Up>", lambda _e: (self.move(-1), "break")[1])
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            panel.bind(key, lambda _e: (self.choose(self.active), "break")[1])
        panel.bind("<Destroy>", lambda _e: self._forget(panel), add="+")
        root = top._root()
        if not getattr(root, "_popup_menu_watch", False):
            root._popup_menu_watch = True  # type: ignore[attr-defined]
            root.bind_all("<ButtonPress-1>", PopupMenu._pressed_elsewhere, add="+")
            root.bind_all("<ButtonPress-3>", PopupMenu._pressed_elsewhere, add="+")
        panel.update_idletasks()
        width = max(panel.winfo_reqwidth(), px(200))
        height = panel.winfo_reqheight()
        room_x = max(top.winfo_width(), width + px(16))
        room_y = max(top.winfo_height(), height + px(16))
        left = max(px(8), min(x - top.winfo_rootx(), room_x - width - px(8)))
        upper = max(px(8), min(y - top.winfo_rooty() + px(4), room_y - height - px(8)))
        self._focus_before = top.focus_get()
        start = upper - px(6) if theme.motion else upper
        panel.place(x=left, y=start, width=width)
        panel.lift()
        panel.focus_set()
        if theme.motion:
            self._slide(left, start, upper, 0)

    def _slide(self, left: int, start: int, end: int, step: int) -> None:
        """Three short frames: the panel settles down into place."""
        panel = self.panel
        self._slide_after = None
        if panel is None:
            return
        step += 1
        with contextlib.suppress(tk.TclError):
            panel.place_configure(x=left, y=start + (end - start) * step // 3)
            if step < 3:
                self._slide_after = panel.after(22, self._slide, left, start, end, step)

    def _forget(self, panel: tk.Frame) -> None:
        if self.panel is panel:
            self.panel = None
            if PopupMenu._open is self:
                PopupMenu._open = None

    @staticmethod
    def _pressed_elsewhere(event: tk.Event) -> None:
        menu = PopupMenu._open
        if menu is None or menu.panel is None:
            return
        widget = event.widget
        while widget is not None and not isinstance(widget, str):
            if widget is menu.panel:
                return
            widget = getattr(widget, "master", None)
        if event.widget is menu._anchor:
            PopupMenu._dismissed = (menu._anchor, time.monotonic())
        menu.close()

    def _set_active(self, index: int | None) -> None:
        if index == self.active:
            return
        c = self.theme.c
        for which, lit in ((self.active, False), (index, True)):
            for part in self._rows.get(which, []) if which is not None else []:
                with contextlib.suppress(tk.TclError):
                    if isinstance(part, tk.Label) and str(part.cget("highlightthickness")) != "0":
                        continue  # a key cap keeps its own surface
                    part.configure(bg=c["nav_active"] if lit else c["card_hover"])
                    pair = getattr(part, "pair", None)
                    if pair is not None:
                        part.configure(image=pair[1 if lit else 0])
        self.active = index

    def move(self, step: int) -> None:
        choices = self.commands()
        if not choices:
            return
        if self.active not in choices:
            self._set_active(choices[0 if step > 0 else -1])
        else:
            self._set_active(choices[(choices.index(self.active) + step) % len(choices)])

    def choose(self, index: int | None) -> None:
        if index is None or index not in self.commands():
            return
        self.close()
        self.invoke(index)

    def close(self) -> None:
        panel, self.panel = self.panel, None
        if PopupMenu._open is self:
            PopupMenu._open = None
        if panel is None:
            return
        with contextlib.suppress(tk.TclError):
            if self._slide_after is not None:
                panel.after_cancel(self._slide_after)
            self._slide_after = None
            had_focus = panel.focus_get() is panel
            panel.destroy()
            if had_focus and self._focus_before is not None:
                self._focus_before.focus_set()
        self._rows, self._images, self._focus_before = {}, [], None


def icon_badge(master: tk.Misc, theme: Theme, name: str, size: int = 36,
               color: str | None = None, bg: str | None = None, gap: int = 0) -> tk.PhotoImage:
    """An icon on a softly tinted rounded square, as one image: the mark of an empty state,
    a list row or a kind of file. ``gap`` adds clear space on its right, for a label that
    shows the badge next to its text. Keep a reference to the image where it is used."""
    c = theme.c
    side = theme.px(size)
    color = color or c["accent"]
    bg = bg or str(master.cget("bg"))
    tint = mix_color(color, bg, 0.86)
    base = glass_image(master, side, side, side * 0.28, tint, bg, mix_color(color, tint, 0.72))
    glyph = int(side * 0.5)
    icon = icon_image(master, name, glyph, color, tint)
    image = tk.PhotoImage(master=master, width=side + theme.px(gap), height=side)
    image.put(bg, to=(0, 0, side + theme.px(gap), side))
    image.tk.call(image, "copy", base)
    offset = (side - glyph) // 2
    image.tk.call(image, "copy", icon, "-to", offset, offset)
    return image


def tooltip(widget: tk.Misc, theme: Theme, text: str, title: str = "",
            when: Callable[[], bool] | None = None) -> None:
    """Hover (or keyboard focus) for half a second shows a small card below the widget.
    With ``title`` the card gets a bold heading over the (wrapped) body text — used by the
    ``?`` help markers for a fuller explanation."""
    state: dict[str, Any] = {"after": None, "tip": None}

    def show() -> None:
        state["after"] = None
        if when is not None and not when():
            return
        with contextlib.suppress(tk.TclError):
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            c = theme.c
            surface = c["card_hover"]
            box = tk.Frame(tip, bg=surface, padx=theme.px(10), pady=theme.px(7),
                           highlightthickness=1, highlightbackground=c["border_strong"])
            box.pack()
            if title:
                tk.Label(box, text=title, bg=surface, fg=c["text"], anchor="w", justify="left",
                         font=theme.font(9, "bold")).pack(fill="x")
            tk.Label(box, text=text, bg=surface, fg=c["muted"] if title else c["text"],
                     font=theme.font(9), justify="left", anchor="w",
                     wraplength=theme.px(260) if title else theme.px(420),
                     pady=theme.px(2) if title else 0).pack(fill="x")
            tip.update_idletasks()
            x = widget.winfo_rootx() + widget.winfo_width() // 2 - tip.winfo_reqwidth() // 2
            y = widget.winfo_rooty() + widget.winfo_height() + theme.px(6)
            # Never off the edge of the screen; above the widget when there is no room below.
            x = max(4, min(x, tip.winfo_screenwidth() - tip.winfo_reqwidth() - 4))
            if y + tip.winfo_reqheight() > tip.winfo_screenheight() - 4:
                y = widget.winfo_rooty() - tip.winfo_reqheight() - theme.px(6)
            tip.wm_geometry(f"+{x}+{max(0, y)}")
            state["tip"] = tip

    def schedule(_event: tk.Event | None = None) -> None:
        hide()
        state["after"] = widget.after(500, show)

    def hide(_event: tk.Event | None = None) -> None:
        if state["after"] is not None:
            with contextlib.suppress(tk.TclError):
                widget.after_cancel(state["after"])
            state["after"] = None
        if state["tip"] is not None:
            with contextlib.suppress(tk.TclError):
                state["tip"].destroy()
            state["tip"] = None

    for name in ("<Enter>", "<FocusIn>"):
        widget.bind(name, schedule, add="+")
    for name in ("<Leave>", "<FocusOut>", "<ButtonPress>", "<Destroy>"):
        widget.bind(name, hide, add="+")
