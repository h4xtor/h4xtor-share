"""Small Tk widget kit used by the desktop app.

Plain Tk widgets look dated, so the app draws its own rounded buttons,
cards, toggles, pills and progress bars on canvases. Everything is themed
from one palette (light and dark) and scaled for high-DPI screens.
"""

from __future__ import annotations

import contextlib
import platform
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from typing import Any

# "Battle.net" palettes: a near-black blue-grey launcher, dark panels with hairline borders,
# one bright launcher-blue for the actions that matter, and a warm orange for Bluetooth and
# the monkey. Text colours keep at least 4.5:1 against the panels they sit on.
LIGHT = {
    "bg": "#F2F4F8",
    "sidebar": "#E6EAF1",
    "chrome": "#DDE2EA",
    "card": "#FFFFFF",
    "card_hover": "#F5F8FC",
    "border": "#D5DBE5",
    "border_strong": "#BAC3D1",
    "text": "#11151C",
    "muted": "#4E5766",
    "faint": "#5F6877",
    "accent": "#0A6ED1",
    "accent_hover": "#085BB0",
    "accent_press": "#064A90",
    "button": "#0A6ED1",
    "button_hover": "#085BB0",
    "accent_soft": "#DCEBFB",
    "accent_text": "#FFFFFF",
    "accent2": "#0A86D1",
    "accent3": "#C25E00",
    "success": "#13784A",
    "success_soft": "#DCF2E6",
    "warning": "#8A5A10",
    "warning_soft": "#FBEFD9",
    "danger": "#B42318",
    "danger_soft": "#FBE4E1",
    "neutral_soft": "#E7EBF1",
    "nav_active": "#DCEBFB",
    "track": "#DDE2EA",
    "entry": "#FFFFFF",
    "shadow": "#DDE2EA",
    "hero_top": "#CFE2F8",
    "glow": "#3D9BFF",
}

DARK = {
    "bg": "#111318",
    "sidebar": "#0B0D11",
    "chrome": "#08090C",
    "card": "#1A1D24",
    "card_hover": "#22262F",
    "border": "#272B34",
    "border_strong": "#363B46",
    "text": "#F3F5F9",
    "muted": "#AAB1BE",
    "faint": "#8A92A0",
    "accent": "#148EFF",
    "accent_hover": "#3BA2FF",
    "accent_press": "#0A62B8",
    "button": "#0B74DC",
    "button_hover": "#1683F0",
    "accent_soft": "#0D2340",
    "accent_text": "#FFFFFF",
    "accent2": "#45B6FF",
    "accent3": "#FF9F1A",
    "success": "#3CCB7F",
    "success_soft": "#12301F",
    "warning": "#F2B33D",
    "warning_soft": "#352A12",
    "danger": "#FF6B6B",
    "danger_soft": "#3A1C1F",
    "neutral_soft": "#22262F",
    "nav_active": "#17202D",
    "track": "#272B34",
    "entry": "#0F1115",
    "shadow": "#050608",
    "hero_top": "#0A1D3A",
    "glow": "#148EFF",
}

# Avatar colours: bright enough to read a dark letter on (see Avatar).
PLATFORM_STYLE = {
    "android": ("#3CCB7F", "A"),
    "windows": ("#3BA2FF", "W"),
    "linux": ("#F2B33D", "L"),
    "darwin": ("#AAB1BE", "M"),
    "macos": ("#AAB1BE", "M"),
    "all": ("#45B6FF", "★"),
}
AVATAR_LETTER = "#0B0D11"


class Theme:
    def __init__(self, root: tk.Misc, dark: bool) -> None:
        self.dark = dark
        self.c = dict(DARK if dark else LIGHT)
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
    shine: bool = True,
) -> tk.PhotoImage:
    """A rounded pill/panel with smooth (anti-aliased) edges and a glassy light: brighter
    at the top, a thin bright rim along the top edge. Tk cannot smooth polygon edges, so
    this paints each pixel by how much of it the shape covers. ``bg`` may be four colours
    (top-left, top-right, bottom-left, bottom-right) when the widget sits on artwork: the
    corners then blend into it instead of showing a box. Cached per look and size."""
    import math

    key = (master.tk, width, height, radius, fill, bg, ring, ring_width, shine)  # per Tk app
    image = _GLASS_CACHE.get(key)
    if image is not None:
        return image
    if len(_GLASS_CACHE) > 400:
        _GLASS_CACHE.clear()
    def tone(color: str) -> list[float]:  # any Tk colour (a name too) as 0-255 floats
        return [v / 257 for v in master.winfo_rgb(color)]

    rgb = [tone(fill), tone(ring or fill)]
    corners = [tone(c) for c in ((bg,) * 4 if isinstance(bg, str) else bg)]
    radius = max(0.0, min(radius, width / 2, height / 2))
    half_w, half_h = width / 2, height / 2
    rows = []
    for y in range(height):
        v = (y + 0.5) / height
        light = 0.20 * (1 - v) ** 2 - 0.05 * v * v if shine else 0.0
        base = [c + ((255 if light > 0 else 0) - c) * abs(light) for c in rgb[0]]
        qy = abs(y + 0.5 - half_h) - (half_h - radius)
        left = [a + (b - a) * v for a, b in zip(corners[0], corners[2], strict=True)]
        right = [a + (b - a) * v for a, b in zip(corners[1], corners[3], strict=True)]

        def pixel(x: int, qy: float = qy, v: float = v, base: list[float] = base,
                  left: list[float] = left, right: list[float] = right) -> str:
            qx = abs(x + 0.5 - half_w) - (half_w - radius)
            d = math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - radius
            cover = 0.5 - d
            u = (x + 0.5) / width
            back = [a + (b - a) * u for a, b in zip(left, right, strict=True)]
            if cover <= 0:
                return "#" + "".join(_HEX[int(c)] for c in back)
            color = base
            if ring and d > -ring_width - 0.5:  # the outline, smoothed on its inner side
                k = min(1.0, d + ring_width + 0.5)
                color = [a + (b - a) * k for a, b in zip(base, rgb[1], strict=True)]
            elif shine and d > -1.6 and v < 0.5:  # the bright rim catching the light
                k = 0.30 * (1 - v * 2) * min(1.0, d + 1.6)
                color = [a + (255 - a) * k for a in base]
            if cover < 1:
                color = [b + (a - b) * cover for a, b in zip(color, back, strict=True)]
            return "#" + "".join(_HEX[max(0, min(255, int(c)))] for c in color)

        # Only the round ends need working out pixel by pixel: in between, every pixel of a
        # row is the same (fully covered, same distance to the top and bottom edges).
        edge = min(width // 2, int(radius) + 3)
        middle = [pixel(width // 2)] * (width - 2 * edge)
        row = [pixel(x) for x in range(edge)] + middle + [
            pixel(x) for x in range(width - edge, width)]
        rows.append("{" + " ".join(row) + "}")
    image = tk.PhotoImage(master=master, width=width, height=height)
    image.put(" ".join(rows))
    _GLASS_CACHE[key] = image
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
    """Launcher-style button drawn on a canvas: hover, press, and keyboard focus.

    Tab reaches every button; Enter or Space presses the focused one, which shows a
    focus ring. ``size="xl"`` is the big blue "Play"-style button on the Send hero.
    """

    SIZES = {  # font size, horizontal padding, height
        "sm": (9, 10, 28),
        "md": (10, 14, 34),
        "lg": (11, 20, 42),
        "xl": (13, 30, 50),
    }

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
        font_size, pad, height = self.SIZES[size]
        bold = kind in {"primary", "danger"} or size == "xl"
        self._font = theme.font(font_size, "bold" if bold else "normal")
        self._pad = theme.px(pad)
        self._fixed = theme.px(width) if width else None
        self._height = theme.px(height)
        self._label = f"{icon}  {text}" if icon and text else (icon or text)
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
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, self._key_pressed)
        self._draw()

    def _natural(self) -> int:
        # The pill's round ends need room: never less padding than about half its height.
        return self._font.measure(self._label) + 2 * max(self._pad, int(self._height * 0.42))

    def _colors(self) -> tuple[str, str, str]:
        c = self.theme.c
        if not self.enabled:
            return c["neutral_soft"], c["neutral_soft"], c["faint"]
        if self.kind == "primary":
            fill = (
                c["accent_press"] if self._pressed
                else c["button_hover"] if self._hover
                else c["button"]
            )
            return fill, fill, c["accent_text"]
        if self.kind == "danger":
            fill = c["danger"] if self._hover or self._pressed else c["danger_soft"]
            text = c["accent_text"] if self._hover or self._pressed else c["danger"]
            return fill, c["danger"], text
        if self.kind == "ghost":
            fill = (
                c["accent_soft"] if self._pressed
                else c["nav_active"] if self._hover
                else self.cget("bg")
            )
            return fill, fill, c["text"]
        if self.kind == "soft":
            fill = c["nav_active"] if self._pressed else c["accent_soft"]
            return fill, fill, c["accent_hover"] if self._hover else c["accent"]
        fill = (
            c["border"] if self._pressed
            else c["card_hover"] if self._hover
            else c["neutral_soft"]
        )
        border = c["border_strong"] if self._hover else c["border"]
        return fill, border, c["text"]

    def _draw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), self._width) if self.winfo_ismapped() else self._width
        fill, outline, foreground = self._colors()
        bg: str | tuple[str, str, str, str] = self.backdrop or self.cget("bg")
        ring: str | None = outline if outline != fill else None
        if self._focused:
            ring = self.theme.c["accent2"] if self.kind == "primary" else self.theme.c["accent"]
        # A soft pill with smooth edges; glassy unless it is a flat ghost on its background.
        self._image = glass_image(
            self, width, self._height, self._height / 2, fill, bg, ring,
            2.0 if self._focused else 1.0, shine=fill != self.cget("bg") and not self._pressed)
        self.create_image(0, 0, image=self._image, anchor="nw")
        nudge = 1 if self._pressed else 0  # pressed text sinks a pixel
        self.create_text(
            width / 2, self._height / 2 + nudge, text=self._label, fill=foreground,
            font=self._font,
        )

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
        self._draw()

    def set_text(self, text: str) -> None:
        self._text = text
        self._label = f"{self._icon}  {text}" if self._icon and text else (self._icon or text)
        # Measured afresh each time, so a label that gets shorter gives its width back.
        self._width = self._fixed or self._natural()
        self.configure(width=self._width)
        self._draw()


class Toggle(tk.Canvas):
    """iOS/Android style switch."""

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
        self._tw = theme.px(40)
        self._th = theme.px(22)
        super().__init__(
            parent,
            width=self._tw,
            height=self._th,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.bind("<ButtonRelease-1>", lambda _e: self.toggle())
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        c = self.theme.c
        track = c["accent"] if self.value else c["track"]
        round_rect(self, 0, 0, self._tw, self._th, self._th / 2, fill=track, outline=track)
        margin = self.theme.px(3)
        diameter = self._th - 2 * margin
        x = self._tw - margin - diameter if self.value else margin
        self.create_oval(x, margin, x + diameter, margin + diameter, fill="#FFFFFF", outline="")

    def toggle(self) -> None:
        self.set(not self.value)
        if self.command is not None:
            self.command(self.value)

    def set(self, value: bool) -> None:
        self.value = bool(value)
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
            if self.winfo_ismapped():
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
                    light = mix_color("#FFFFFF", self.color, 0.62)
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
        width = self._font.measure(text) + self.theme.px(18)
        height = self.theme.px(20)
        self.configure(width=width)
        self.delete("all")
        round_rect(self, 0, 0, width, height, height / 2, fill=fill, outline=fill)
        self.create_text(width / 2, height / 2, text=text, fill=fg, font=self._font)


class Avatar(tk.Canvas):
    """Coloured circle with a platform letter."""

    def __init__(self, parent: tk.Misc, theme: Theme, platform_name: str, size: int = 40) -> None:
        self.theme = theme
        diameter = theme.px(size)
        super().__init__(
            parent,
            width=diameter,
            height=diameter,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
        )
        color, letter = PLATFORM_STYLE.get(platform_name.lower(), (theme.c["faint"], "?"))
        self.create_oval(1, 1, diameter - 1, diameter - 1, fill=color, outline=color)
        self.create_text(
            diameter / 2,
            diameter / 2,
            text=letter,
            fill=AVATAR_LETTER,
            font=theme.font(max(9, size // 3), "bold"),
        )


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
        radius: int = 6,
    ) -> None:
        self.theme = theme
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
        self._draw()

    def _resized(self, event: tk.Event) -> None:
        self.itemconfigure(self._window, width=max(1, event.width - 2 * self.padding))
        self._draw()

    def set_colors(self, fill: str | None = None, outline: str | None = None) -> None:
        if fill:
            self.fill = fill
            self.body.configure(bg=fill)
        if outline:
            self.outline = outline
        self._draw()

    def _draw(self) -> None:
        self.delete("bg")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 4 or height < 4:
            return
        round_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            self.radius,
            fill=self.fill,
            outline=self.outline,
            tags=("bg",),
        )
        # Panels catch a faint line of light along the top edge, strongest at the left.
        r = self.radius
        span = width - 2 * r
        segments = 16
        for index in range(segments):
            f = index / segments
            x1 = r + f * span
            self.create_line(x1, 1, x1 + span / segments + 1, 1, tags=("bg",), width=1,
                             fill=mix_color("#FFFFFF", self.outline, 0.86 + 0.14 * f))
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
        frame = tk.Frame(self.root, bg=c["card"], highlightthickness=1,
                         highlightbackground=c["border_strong"])
        tk.Frame(frame, bg=accent, width=px(4)).pack(side="left", fill="y")
        inner = tk.Frame(frame, bg=c["card"], padx=px(14), pady=px(11))
        inner.pack(side="left", fill="both")
        tk.Label(
            inner, text=self.ICONS.get(tone, "●"), fg=accent, bg=c["card"],
            font=self.theme.font(11, "bold"), width=2,
        ).pack(side="left", padx=(0, px(6)))
        tk.Label(
            inner,
            text=text,
            fg=c["text"],
            bg=c["card"],
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
            frame.place(relx=1.0, rely=1.0, anchor="se", y=-self.theme.px(24),
                        x=-self.theme.px(24) + self.theme.px(self.SLIDE[step]))
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
        self.configure(bg=theme.c["bg"])
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
    return tk.Entry(
        parent,
        textvariable=variable,
        bg=c["entry"],
        fg=c["text"],
        insertbackground=c["text"],
        relief="flat",
        highlightthickness=1,
        highlightbackground=c["border"],
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
    """The hero's key art: a deep-blue sky, a big soft glow where the monkey stands, light
    rays falling from the top right, darker on the left so the words read, melting into
    the page at the bottom. Rendered at 1/``step`` size (Tk has no blur), then zoomed."""
    import math

    w, h = max(2, width // step), max(2, height // step)
    top, bottom = _rgb(c["hero_top"]), _rgb(c["bg"])
    glows = (  # centre u, centre v, sigma u, sigma v, strength, colour
        (0.80, 0.55, 0.17, 0.42, 0.62, _rgb(c["glow"])),
        (0.96, 0.02, 0.10, 0.22, 0.34, _rgb(c["accent2"])),
        (0.22, -0.10, 0.28, 0.30, 0.28, _rgb("#0B5FC8")),
    )
    cols = [[math.exp(-((x / w - g[0]) ** 2) / (2 * g[2] ** 2)) for x in range(w)] for g in glows]
    rows = [[math.exp(-((y / h - g[1]) ** 2) / (2 * g[3] ** 2)) for y in range(h)] for g in glows]
    aspect = w / h
    lines = []
    for y in range(h):
        v = y / h
        t = v * v * (3 - 2 * v)
        base = [top[i] + (bottom[i] - top[i]) * t for i in range(3)]
        fade = max(0.0, (v - 0.72) / 0.28)
        fade = fade * fade * (3 - 2 * fade)
        row = []
        for x in range(w):
            u = x / w
            r, g, b = base
            # Quieter on the left, under the words: towards the page colour (dark or light).
            shade = (1 - u) ** 2 * 0.45
            r, g, b = r + (bottom[0] - r) * shade, g + (bottom[1] - g) * shade, b + (
                bottom[2] - b) * shade
            for index, glow in enumerate(glows):
                k = glow[4] * cols[index][x] * rows[index][y]
                gr, gg, gb = glow[5]
                r, g, b = r + (gr - r) * k, g + (gg - g) * k, b + (gb - b) * k
            ray = 0.0
            for offset in (0.30, 0.48, 0.62):  # three soft diagonal beams
                d = (u - 0.95) * aspect * 0.55 + (v + 0.2) * 0.9 - offset * aspect * 0.55
                ray += math.exp(-(d * d) / 0.0018) * 0.07 * max(0.0, 1 - v * 1.1)
            r, g, b = r + (255 - r) * ray, g + (255 - g) * ray, b + (255 - b) * ray
            r, g, b = r + (bottom[0] - r) * fade, g + (bottom[1] - g) * fade, b + (
                bottom[2] - b) * fade
            row.append("#" + _HEX[int(r)] + _HEX[int(g)] + _HEX[int(b)])
        lines.append("{" + " ".join(row) + "}")
    small = tk.PhotoImage(master=master, width=w, height=h)
    small.put(" ".join(lines))
    return small.zoom(step) if step > 1 else small


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
            if self._rng.random() < 0.3:
                self.point()  # stops and shows you the devices
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
    """The Send page's key art, Battle.net style: deep-blue light, drifting embers and
    the monkey as the character. The words are drawn straight onto the art (set_words);
    the owner packs its buttons into ``buttons``, which sits under the words.

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
        self.buttons = tk.Frame(self, bg=theme.c["hero_top"])
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
        step = 2 if width <= 1600 else 3
        self._image = render_backdrop(self, width, height, self.theme.c, step)
        self.delete("backdrop")
        self.create_image(0, 0, image=self._image, anchor="nw", tags=("backdrop",))
        self.tag_lower("backdrop")
        size = min(height * 0.6, width * 0.15)
        self.actor.place(width * 0.80, height * 0.93, size, roam=width * 0.07)
        self._spawn_embers(width, height)
        self._layout_words()

    def set_words(
        self, eyebrow: str, title: str, status: str = "", dot: str | None = None, hint: str = ""
    ) -> None:
        """Eyebrow (small, blue), title (big, uppercase), a status line with a coloured
        dot, and a hint under the buttons."""
        words = (eyebrow, title.upper(), status, dot or self.theme.c["faint"], hint)
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
        x = px(48)
        title_size = 34 if len(title) <= 14 else 28 if len(title) <= 20 else 22
        fonts = (self.theme.font(9, "bold"), self.theme.hero_font(title_size),
                 self.theme.font(10))
        y = height * 0.15
        self.create_text(x, y, text=eyebrow, fill=c["accent2"], font=fonts[0], anchor="nw",
                         tags=("words",))
        y += fonts[0].metrics("linespace") + px(2)
        self.create_text(x - px(2), y, text=title, fill=c["text"], font=fonts[1], anchor="nw",
                         width=int(width * 0.58), tags=("words",))
        y += fonts[1].metrics("linespace") * (1 if fonts[1].measure(title) < width * 0.58
                                               else 2) + px(2)
        if status:
            r = px(4)
            mid = y + fonts[2].metrics("linespace") / 2
            self.create_oval(x, mid - r, x + 2 * r, mid + r, fill=dot, outline="",
                             tags=("words",))
            self.create_text(x + 2 * r + px(8), y, text=status, fill=c["muted"], font=fonts[2],
                             anchor="nw", tags=("words",))
            y += fonts[2].metrics("linespace")
        y += px(16)
        self.coords(self._buttons_item, x, y)
        self.refresh_buttons()
        if hint:
            y += max(self.buttons.winfo_reqheight(), px(50)) + px(12)
            self.create_text(x, y, text=hint, fill=c["faint"], font=self.theme.font(9),
                             anchor="nw", width=int(width * 0.55), tags=("words",))

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
    """Devices as launcher game icons: square tiles with the platform, name and status.

    The selected tile glows blue; a pointer over a tile lifts it a little. ``nodes`` are
    dicts with id, name, platform, online, selected and sub (a short status line);
    ``on_add`` adds a dashed "+" tile at the end.
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
        self._tw, self._th = theme.px(118), theme.px(150)
        self._phase = 0.0
        self._pulse_after: str | None = None
        self.set_nodes([])

    def set_nodes(self, nodes: list[dict[str, Any]]) -> None:
        if nodes == self.nodes and self.tiles:
            return
        self.nodes = [dict(node) for node in nodes]
        for tile in self.winfo_children():
            tile.destroy()
        self.tiles = {}
        for node in self.nodes:
            self.tiles[node["id"]] = self._tile(node)
        if self.on_add is not None:
            self._tile({"id": "+", "name": "Forbind ny", "sub": "QR · IP · Bluetooth"})
        if self._pulse_after is None and any(node.get("sending") for node in self.nodes):
            self._pulse_after = self.after(60, self._pulse)

    def _pulse(self) -> None:
        """The tile being sent to breathes blue until the send is over."""
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
        px = self.theme.px
        tile = tk.Canvas(self, width=self._tw, height=self._th, bg=self.theme.c["bg"],
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        tile.pack(side="left", padx=(0, px(12)))
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

    def _paint(self, tile: tk.Canvas) -> None:
        c, px = self.theme.c, self.theme.px
        node = tile.node  # type: ignore[attr-defined]
        hover = tile.hover  # type: ignore[attr-defined]
        w, h = self._tw, self._th
        tile.delete("all")
        lift = px(3) if hover else 0
        box = (px(4), px(4) - lift, w - px(4), w - px(16) - lift)
        selected = node.get("selected")
        if node["id"] == "+":
            round_rect(tile, *box, px(6), fill=c["bg"], outline=c["border_strong"], dash=(4, 4))
            tile.create_text((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, text="+",
                             fill=c["accent"] if hover else c["muted"],
                             font=self.theme.font(26))
        else:
            if selected:  # a blue glow around the selected tile
                for step, amount in ((3, 0.78), (2, 0.6), (1, 0.4)):
                    grow = px(step)
                    round_rect(tile, box[0] - grow, box[1] - grow, box[2] + grow, box[3] + grow,
                               px(7), fill="", outline=mix_color(c["accent"], c["bg"], amount),
                               width=2)
            fill = c["card_hover"] if hover else c["card"]
            outline = c["accent"] if selected else c["border_strong"] if hover else c["border"]
            if node.get("sending"):
                import math

                outline = mix_color(c["accent2"], c["border"], 0.5 - 0.5 * math.sin(self._phase))
            width = 2 if selected or node.get("sending") else 1
            round_rect(tile, *box, px(6), fill=fill, outline=outline, width=width)
            color, letter = PLATFORM_STYLE.get(str(node.get("platform", "")).lower(),
                                               (c["faint"], "?"))
            if not node.get("online"):
                color = mix_color(color, c["card"], 0.55)
            cx, cy, r = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, px(22)
            tile.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")
            tile.create_text(cx, cy, text=letter, fill=AVATAR_LETTER,
                             font=self.theme.font(15, "bold"))
            dot = c["success"] if node.get("online") else c["faint"]
            tile.create_oval(box[2] - px(16), box[1] + px(8), box[2] - px(8), box[1] + px(16),
                             fill=dot, outline=fill, width=2)
        name = node["name"] if len(node["name"]) <= 14 else node["name"][:13] + "…"
        tile.create_text(w / 2, w - px(4), text=name, anchor="n",
                         fill=c["text"] if node.get("online") or node["id"] == "+" else c["muted"],
                         font=self.theme.font(9, "bold"))
        tile.create_text(w / 2, w + px(13), text=node.get("sub", ""), anchor="n",
                         fill=c["accent"] if selected else c["faint"], font=self.theme.font(8))
        if tile.focused:  # type: ignore[attr-defined]
            round_rect(tile, 1, 1, w - 1, h - 1, px(6), fill="", outline=c["accent2"], width=2)


def tooltip(widget: tk.Misc, theme: Theme, text: str) -> None:
    """Hover (or keyboard focus) for half a second shows *text* in a small label below."""
    state: dict[str, Any] = {"after": None, "tip": None}

    def show() -> None:
        state["after"] = None
        with contextlib.suppress(tk.TclError):
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            c = theme.c
            tk.Label(tip, text=text, bg=c["card"], fg=c["text"], font=theme.font(9),
                     padx=theme.px(8), pady=theme.px(4), highlightthickness=1,
                     highlightbackground=c["border_strong"]).pack()
            x = widget.winfo_rootx() + widget.winfo_width() // 2 - tip.winfo_reqwidth() // 2
            y = widget.winfo_rooty() + widget.winfo_height() + theme.px(6)
            tip.wm_geometry(f"+{max(0, x)}+{y}")
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
