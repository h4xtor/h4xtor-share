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

# "Aurora" palettes (the mix design): a deep night-blue base with a teal → sky accent,
# a warm orange for Bluetooth and the monkey, and quiet glass-like card borders.
LIGHT = {
    "bg": "#F4F6FB",
    "sidebar": "#EDF1F8",
    "card": "#FFFFFF",
    "card_hover": "#F3F7FB",
    "border": "#DDE3EE",
    "border_strong": "#C9D2E2",
    "text": "#0F172A",
    "muted": "#55607A",
    "faint": "#8A93AA",
    "accent": "#0D9488",
    "accent_hover": "#0F766E",
    "accent_soft": "#DDF4F1",
    "accent_text": "#FFFFFF",
    "accent2": "#0284C7",
    "accent3": "#EA580C",
    "success": "#0F8A5F",
    "success_soft": "#DDF3EA",
    "warning": "#B7791F",
    "warning_soft": "#FBF0DC",
    "danger": "#C2412D",
    "danger_soft": "#FBE5E1",
    "neutral_soft": "#E9EDF5",
    "nav_active": "#DDF4F1",
    "track": "#E3E8F1",
    "entry": "#FFFFFF",
    "shadow": "#E3E8F1",
}

DARK = {
    "bg": "#0E1022",
    "sidebar": "#0A0C1B",
    "card": "#161A33",
    "card_hover": "#1C2140",
    "border": "#262B4A",
    "border_strong": "#343A63",
    "text": "#EEF2FF",
    "muted": "#A3ABC6",
    "faint": "#6E7698",
    "accent": "#2DD4BF",
    "accent_hover": "#5EEAD4",
    "accent_soft": "#123A3E",
    "accent_text": "#0A0B16",
    "accent2": "#38BDF8",
    "accent3": "#FB923C",
    "success": "#34D399",
    "success_soft": "#123329",
    "warning": "#FBBF24",
    "warning_soft": "#3A3015",
    "danger": "#F87171",
    "danger_soft": "#3D1E24",
    "neutral_soft": "#1E2342",
    "nav_active": "#13303A",
    "track": "#232847",
    "entry": "#12152B",
    "shadow": "#070815",
}

PLATFORM_STYLE = {
    "android": ("#3DDC84", "A"),
    "windows": ("#2F7BEA", "W"),
    "linux": ("#E8A33D", "L"),
    "darwin": ("#8E8E93", "M"),
    "macos": ("#8E8E93", "M"),
    "all": ("#2DD4BF", "★"),
}


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
    """Rounded, hover-aware button drawn on a canvas."""

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
        self._hover = False
        self._text = text
        self._icon = icon
        font_size = {"sm": 9, "md": 10, "lg": 11}[size]
        self._font = theme.font(font_size, "bold" if kind in {"primary", "danger"} else "normal")
        pad_x = theme.px({"sm": 10, "md": 14, "lg": 20}[size])
        height = theme.px({"sm": 28, "md": 34, "lg": 42}[size])
        label = f"{icon}  {text}" if icon and text else (icon or text)
        natural = self._font.measure(label) + 2 * pad_x
        self._width = theme.px(width) if width else natural
        self._height = height
        background = bg if bg is not None else parent.cget("bg")
        super().__init__(
            parent,
            width=self._width,
            height=height,
            bg=background,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._label = label
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._clicked)
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    def _colors(self) -> tuple[str, str, str]:
        c = self.theme.c
        if not self.enabled:
            return c["neutral_soft"], c["neutral_soft"], c["faint"]
        if self.kind == "primary":
            fill = c["accent_hover"] if self._hover else c["accent"]
            return fill, fill, c["accent_text"]
        if self.kind == "danger":
            fill = c["danger"] if self._hover else c["danger_soft"]
            return fill, c["danger"], c["accent_text"] if self._hover else c["danger"]
        if self.kind == "ghost":
            fill = c["nav_active"] if self._hover else self.cget("bg")
            return fill, fill, c["text"]
        if self.kind == "soft":
            fill = c["accent_soft"]
            return fill, fill, c["accent_hover"] if self._hover else c["accent"]
        fill = c["card_hover"] if self._hover else c["card"]
        border = c["border_strong"] if self._hover else c["border"]
        return fill, border, c["text"]

    def _draw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), self._width) if self.winfo_ismapped() else self._width
        fill, outline, foreground = self._colors()
        round_rect(
            self,
            1,
            1,
            width - 1,
            self._height - 1,
            self.theme.px(9),
            fill=fill,
            outline=outline,
        )
        self.create_text(
            width / 2, self._height / 2, text=self._label, fill=foreground, font=self._font
        )

    def _set_hover(self, value: bool) -> None:
        self._hover = value and self.enabled
        self._draw()

    def _clicked(self, event: tk.Event) -> None:
        if not self.enabled or self.command is None:
            return
        if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def set_text(self, text: str) -> None:
        self._text = text
        self._label = f"{self._icon}  {text}" if self._icon and text else (self._icon or text)
        self._width = max(self._width, self._font.measure(self._label) + self.theme.px(28))
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
    def __init__(self, parent: tk.Misc, theme: Theme, height: int = 6) -> None:
        self.theme = theme
        self.fraction = 0.0
        self.color = theme.c["accent"]
        self._h = theme.px(height)
        super().__init__(parent, height=self._h, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, fraction: float, color: str | None = None) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        if color:
            self.color = color
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 10)
        radius = self._h / 2
        c = self.theme.c
        round_rect(self, 0, 0, width, self._h, radius, fill=c["track"], outline=c["track"])
        filled = width * self.fraction
        if filled >= self._h:
            round_rect(self, 0, 0, filled, self._h, radius, fill=self.color, outline=self.color)
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
            fill="#FFFFFF",
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
        radius: int = 14,
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
        item = round_rect(
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
        self.tag_lower(item)


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
    """Transient message in the bottom-right corner of the window."""

    def __init__(self, root: tk.Misc, theme: Theme) -> None:
        self.root = root
        self.theme = theme
        self._frame: tk.Frame | None = None
        self._after: str | None = None

    def show(self, text: str, tone: str = "neutral", duration_ms: int = 3500) -> None:
        self.hide()
        c = self.theme.c
        background = c["text"]
        foreground = c["bg"]
        accent = {
            "success": c["success"],
            "danger": c["danger"],
            "warning": c["warning"],
        }.get(tone, c["accent"])
        frame = tk.Frame(self.root, bg=background, padx=self.theme.px(16), pady=self.theme.px(11))
        tk.Label(frame, text="●", fg=accent, bg=background, font=self.theme.font(10)).pack(
            side="left", padx=(0, self.theme.px(10))
        )
        tk.Label(
            frame,
            text=text,
            fg=foreground,
            bg=background,
            font=self.theme.font(10),
            wraplength=self.theme.px(380),
            justify="left",
        ).pack(side="left")
        frame.place(relx=1.0, rely=1.0, x=-self.theme.px(24), y=-self.theme.px(24), anchor="se")
        frame.lift()
        self._frame = frame
        self._after = self.root.after(duration_ms, self.hide)

    def hide(self) -> None:
        if self._after is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._after)
            self._after = None
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
    """Draw the mascot centred on (cx, cy). Eyes carry the extra tag ``<tag>-eye`` for blinking."""
    s = size / 100.0
    ox, oy = cx - size / 2, cy - size / 2

    def circle(x: float, y: float, r: float, fill: str, extra: tuple[str, ...] = ()) -> None:
        canvas.create_oval(ox + (x - r) * s, oy + (y - r) * s, ox + (x + r) * s, oy + (y + r) * s,
                           fill=fill, outline="", tags=(tag, *extra))

    for x in (16, 84):  # ears
        circle(x, 50, 14, MONKEY_BROWN)
        circle(x, 50, 8, MONKEY_INNER)
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
                      style="arc", outline=MONKEY_DARK, width=max(1.5, 2.6 * s), tags=(tag,))


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


class OrbitMap(tk.Canvas):
    """The mix design's device map: the monkey (this computer) in the middle, devices on an orbit.

    A dashed ring turns slowly, a ring pulses out from the monkey, beams join it to the
    devices and small lights travel along a beam while something is being sent. The
    monkey blinks now and then and hops when a send has landed. Click a device to pick it.
    """

    FRAME_MS = 50

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        size: int = 360,
        bg: str | None = None,
        on_pick: Callable[[str], None] | None = None,
        on_add: Callable[[], None] | None = None,
        label: str = "",
    ) -> None:
        self.theme = theme
        self.size = size
        self.base = bg or theme.c["bg"]
        super().__init__(parent, width=size, height=size, bg=self.base, highlightthickness=0, bd=0)
        self.on_pick = on_pick
        self.on_add = on_add
        self.nodes: list[dict[str, Any]] = []
        self.sending: set[str] = set()
        self.label = label
        self._tick = 0
        self._hop = 0
        self._blink = 0
        self._after: str | None = None
        self.bind("<Destroy>", lambda _e: self._stop(), add="+")
        self.bind("<Map>", lambda _e: self._start(), add="+")
        self._draw()

    # ------------------------------------------------------------- public api
    def set_nodes(self, nodes: list[dict[str, Any]]) -> None:
        """Each node: id, name, sub (one short line), online (bool), selected (bool)."""
        if nodes != self.nodes:
            self.nodes = [dict(node) for node in nodes]
            self._draw()

    def set_sending(self, ids: set[str]) -> None:
        if ids != self.sending:
            self.sending = set(ids)
            self._draw()

    def set_label(self, text: str) -> None:
        if text != self.label:
            self.label = text
            self.itemconfigure("hub-label", text=text)

    def celebrate(self) -> None:
        self._hop = 18

    # --------------------------------------------------------------- drawing
    @property
    def center(self) -> float:
        return self.size / 2

    def _positions(self) -> list[tuple[float, float]]:
        import math

        count = len(self.nodes) + (1 if self.on_add else 0)
        radius = self.size * 0.37
        out = []
        for index in range(count):
            angle = math.radians(-35 + index * (360 / max(count, 1)) if count > 1 else -35)
            out.append(
                (self.center + radius * math.cos(angle), self.center + radius * math.sin(angle))
            )
        return out

    def _draw(self) -> None:
        c = self.theme.c
        px = self.theme.px
        self.delete("all")
        mid = self.center
        ring = self.size * 0.43
        for index in range(36):  # dashed outer orbit (rotated each frame)
            self.create_arc(mid - ring, mid - ring, mid + ring, mid + ring, start=index * 10,
                            extent=4, style="arc", outline=c["border_strong"], width=1,
                            tags=("orbit",))
        inner = self.size * 0.26
        self.create_oval(mid - inner, mid - inner, mid + inner, mid + inner,
                         outline=c["border"], width=1)
        self.create_oval(mid, mid, mid, mid, outline=c["accent"], width=2, tags=("pulse",))
        positions = self._positions()
        for node, (x, y) in zip(self.nodes, positions, strict=False):
            live = node.get("online") and (node.get("selected") or node["id"] in self.sending)
            self.create_line(mid, mid, x, y, fill=c["accent"] if live else c["border"],
                             width=2 if live else 1, dash=(4, 6), tags=("beam",))
        hub = self.size * 0.17
        self.create_oval(mid - hub, mid - hub, mid + hub, mid + hub, fill=c["card"],
                         outline=c["accent"], width=2)
        draw_monkey(self, mid, mid, hub * 1.35, "monkey")
        self.create_text(mid, mid + hub + px(14), text=self.label, fill=c["muted"],
                         font=self.theme.font(9, family=self.theme.mono), tags=("hub-label",))
        node_r = self.size * 0.12
        for node, (x, y) in zip(self.nodes, positions, strict=False):
            tag = f"node-{node['id']}"
            ring_color = (
                c["accent"] if node.get("selected") else
                c["accent2"] if node["id"] in self.sending else c["border_strong"]
            )
            self.create_oval(x - node_r, y - node_r, x + node_r, y + node_r,
                             fill=c["card"] if node.get("online") else c["sidebar"],
                             outline=ring_color, width=2, tags=(tag, "node"))
            name = node["name"] if len(node["name"]) <= 11 else node["name"][:10] + "…"
            self.create_text(x, y - px(6), text=name, tags=(tag, "node"),
                             fill=c["text"] if node.get("online") else c["muted"],
                             font=self.theme.font(9, "bold"))
            self.create_text(x, y + px(9), text=node.get("sub", ""), tags=(tag, "node"),
                             fill=c["accent"] if node.get("online") else c["faint"],
                             font=self.theme.font(8, family=self.theme.mono))
            self.tag_bind(tag, "<Button-1>", lambda _e, key=node["id"]: self._pick(key))
            self.tag_bind(tag, "<Enter>", lambda _e: self.configure(cursor="hand2"))
            self.tag_bind(tag, "<Leave>", lambda _e: self.configure(cursor=""))
        if self.on_add and len(positions) > len(self.nodes):
            x, y = positions[len(self.nodes)]
            r = node_r * 0.72
            self.create_oval(x - r, y - r, x + r, y + r, outline=c["border_strong"], dash=(3, 4),
                             width=1, tags=("add",))
            self.create_text(x, y, text="+", fill=c["muted"], font=self.theme.font(16),
                             tags=("add",))
            self.tag_bind("add", "<Button-1>", lambda _e: self.on_add and self.on_add())
            self.tag_bind("add", "<Enter>", lambda _e: self.configure(cursor="hand2"))
            self.tag_bind("add", "<Leave>", lambda _e: self.configure(cursor=""))
        self._dots = []
        for node, (x, y) in zip(self.nodes, positions, strict=False):
            if node["id"] in self.sending:
                for _ in range(2):
                    dot = self.create_oval(0, 0, 0, 0, fill=c["accent"], outline="",
                                           tags=("dot",))
                    self._dots.append((dot, x, y))
        self.tag_raise("node")

    def _pick(self, key: str) -> None:
        if self.on_pick:
            self.on_pick(key)

    # ------------------------------------------------------------- animation
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
            if self.winfo_ismapped():
                self._animate()
        except tk.TclError:
            return
        self._after = self.after(self.FRAME_MS, self._frame)

    def _animate(self) -> None:
        c = self.theme.c
        self._tick += 1
        mid = self.center
        for index, item in enumerate(self.find_withtag("orbit")):
            self.itemconfigure(item, start=(index * 10 + self._tick * 0.6) % 360)
        phase = (self._tick % 60) / 60.0  # pulse every 3 s
        hub = self.size * 0.17
        r = hub + phase * self.size * 0.17
        self.coords("pulse", mid - r, mid - r, mid + r, mid + r)
        self.itemconfigure("pulse", outline=mix_color(c["accent"], self.base, phase))
        self.itemconfigure("beam", dashoffset=-(self._tick % 10))
        for index, (dot, x, y) in enumerate(self._dots):
            t = ((self._tick * 0.06) + index * 0.5) % 1.0
            dx, dy = mid + (x - mid) * t, mid + (y - mid) * t
            size = 4 if index % 2 == 0 else 3
            self.coords(dot, dx - size, dy - size, dx + size, dy + size)
        if self._hop:  # bounce after a send landed
            self._hop -= 1
            step = -2 if self._hop % 6 >= 3 else 2
            self.move("monkey", 0, step)
            self.move("monkey-eye", 0, step)
        self._blink = (self._blink + 1) % 100  # blink every 5 s
        state = "hidden" if self._blink in (0, 1, 2) else "normal"
        self.itemconfigure("monkey-eye", state=state)

