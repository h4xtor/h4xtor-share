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

# Palettes modelled on Claude.ai: warm paper whites, warm charcoal darks,
# one terracotta accent and very quiet borders.
LIGHT = {
    "bg": "#FAF9F5",
    "sidebar": "#F5F4ED",
    "card": "#FFFFFF",
    "card_hover": "#F8F7F2",
    "border": "#E8E6DC",
    "border_strong": "#D9D6C9",
    "text": "#141413",
    "muted": "#73726C",
    "faint": "#A3A19A",
    "accent": "#C6613F",
    "accent_hover": "#B0532F",
    "accent_soft": "#F5E6DE",
    "accent_text": "#FFFFFF",
    "success": "#2E8B57",
    "success_soft": "#E3F2E9",
    "warning": "#B7791F",
    "warning_soft": "#FBF0DC",
    "danger": "#C2412D",
    "danger_soft": "#FBE5E1",
    "neutral_soft": "#EFEDE6",
    "nav_active": "#EAE8E0",
    "track": "#ECE9E0",
    "entry": "#FFFFFF",
    "shadow": "#EDEAE1",
}

DARK = {
    "bg": "#262624",
    "sidebar": "#1F1E1D",
    "card": "#30302E",
    "card_hover": "#363633",
    "border": "#3E3E3A",
    "border_strong": "#4D4D48",
    "text": "#F5F4EE",
    "muted": "#A6A39A",
    "faint": "#77756D",
    "accent": "#D97757",
    "accent_hover": "#E38A6C",
    "accent_soft": "#3E2D25",
    "accent_text": "#FFFFFF",
    "success": "#5BC38E",
    "success_soft": "#24372B",
    "warning": "#E2A84B",
    "warning_soft": "#3A2F1C",
    "danger": "#EF6B55",
    "danger_soft": "#41261F",
    "neutral_soft": "#383835",
    "nav_active": "#2E2E2B",
    "track": "#41413C",
    "entry": "#30302E",
    "shadow": "#1A1A19",
}

PLATFORM_STYLE = {
    "android": ("#3DDC84", "A"),
    "windows": ("#2F7BEA", "W"),
    "linux": ("#E8A33D", "L"),
    "darwin": ("#8E8E93", "M"),
    "macos": ("#8E8E93", "M"),
    "all": ("#D97757", "★"),
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
        return self.font(size, "normal", self.serif)

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


class Monkey(tk.Canvas):
    """A small friendly monkey mascot, drawn with vector shapes (scales cleanly)."""

    BROWN = "#8B5A3C"
    FACE = "#F2D3B1"
    INNER = "#E9B98F"
    DARK = "#3B2A20"

    def __init__(self, parent: tk.Misc, theme: Theme, size: int = 64) -> None:
        super().__init__(
            parent, width=size, height=size, bg=theme.c["bg"], highlightthickness=0, bd=0
        )
        self._draw(size / 100.0)

    def _circle(self, x: float, y: float, r: float, s: float, fill: str) -> None:
        self.create_oval((x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s, fill=fill, outline="")

    def _draw(self, s: float) -> None:
        for x in (16, 84):  # ears
            self._circle(x, 50, 14, s, self.BROWN)
            self._circle(x, 50, 8, s, self.INNER)
        self._circle(50, 50, 33, s, self.BROWN)  # head
        self.create_line(44 * s, 19 * s, 50 * s, 11 * s, 55 * s, 18 * s, fill=self.BROWN,
                         width=max(2, 4 * s), smooth=True, capstyle="round")
        self._circle(39, 45, 12, s, self.FACE)  # face lobes
        self._circle(61, 45, 12, s, self.FACE)
        self.create_oval(28 * s, 50 * s, 72 * s, 80 * s, fill=self.FACE, outline="")  # muzzle
        for x in (40, 60):  # eyes
            self._circle(x, 45, 4.4, s, self.DARK)
            self._circle(x + 1.4, 43.4, 1.4, s, "#FFFFFF")
        for x in (46, 54):  # nostrils
            self._circle(x, 60, 1.6, s, self.DARK)
        self.create_arc(40 * s, 58 * s, 60 * s, 74 * s, start=200, extent=140, style="arc",
                        outline=self.DARK, width=max(1.5, 2.6 * s))
