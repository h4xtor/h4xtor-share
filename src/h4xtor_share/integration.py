"""Operating-system integration for the desktop app.

* **Single instance** – a second launch (for example from Explorer's
  *Send to* menu) hands its file list to the running app over a loopback
  socket protected by a random token, then exits.
* **Send to menu** (Windows) – a shortcut in ``shell:sendto`` so any file or
  folder can be sent with a right-click.
* **Start with the computer** – a per-user autostart entry (Windows registry
  ``Run`` key, XDG autostart on Linux, LaunchAgent on macOS).
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

APP_NAME = "h4xtor-share"
INSTANCE_PORT_OFFSET = 1
_SYSTEM = platform.system()


def launch_command() -> list[str]:
    """Command that starts this app (frozen executable or Python module)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    executable = Path(sys.executable)
    if _SYSTEM == "Windows":
        windowed = executable.with_name("pythonw.exe")
        if windowed.exists():
            executable = windowed
    return [str(executable), "-m", "h4xtor_share"]


# -- single instance -----------------------------------------------------------
class InstanceServer:
    """Loopback listener that receives commands from later launches."""

    def __init__(
        self,
        config_directory: Path,
        port: int,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        self.token_path = config_directory / "instance.token"
        self.port = port
        self.handler = handler
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self) -> bool:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", self.port))
        except OSError:
            listener.close()
            return False
        listener.listen(4)
        listener.settimeout(0.5)
        token = secrets.token_hex(16)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(token, encoding="utf-8")
        self._token = token
        self._socket = listener
        self._thread = threading.Thread(target=self._loop, name="h4xtor-instance", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stopping.set()
        if self._socket is not None:
            with contextlib.suppress(OSError):
                self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with contextlib.suppress(OSError):
            self.token_path.unlink()

    def _loop(self) -> None:
        assert self._socket is not None
        while not self._stopping.is_set():
            try:
                connection, _address = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(3)
                data = b""
                try:
                    while not data.endswith(b"\n") and len(data) < 1_000_000:
                        chunk = connection.recv(65536)
                        if not chunk:
                            break
                        data += chunk
                    message = json.loads(data.decode("utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(message, dict):
                    continue
                if not secrets.compare_digest(str(message.get("token", "")), self._token):
                    continue
                with contextlib.suppress(OSError):
                    connection.sendall(b'{"ok":true}\n')
                with contextlib.suppress(Exception):
                    self.handler(message)


def send_to_running_instance(config_directory: Path, port: int, message: dict[str, Any]) -> bool:
    """Deliver *message* to an already running app. True when it was accepted."""
    token_path = config_directory / "instance.token"
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    payload = dict(message)
    payload["token"] = token
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.sendall(json.dumps(payload).encode("utf-8") + b"\n")
            connection.settimeout(3)
            reply = connection.recv(1024)
    except OSError:
        return False
    return b'"ok"' in reply


# -- Send to menu (Windows) ------------------------------------------------------
def send_to_shortcut_path() -> Path | None:
    if _SYSTEM != "Windows":
        return None
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "SendTo" / f"{APP_NAME}.lnk"


def _powershell(script: str) -> None:
    subprocess.run(  # noqa: S603
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        timeout=20,
        creationflags=0x08000000,
    )


def install_send_to() -> Path:
    path = send_to_shortcut_path()
    if path is None:
        raise RuntimeError("The Send to menu is only available on Windows.")
    command = launch_command()
    target = command[0].replace("'", "''")
    arguments = " ".join([*command[1:], "--send"]).replace("'", "''")
    shortcut = str(path).replace("'", "''")
    _powershell(
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('" + shortcut + "');"
        "$s.TargetPath='" + target + "';"
        "$s.Arguments='" + arguments + "';"
        "$s.Description='Send with h4xtor-share';"
        "$s.IconLocation='" + target + ",0';"
        "$s.Save()"
    )
    return path


def remove_send_to() -> None:
    path = send_to_shortcut_path()
    if path is not None:
        with contextlib.suppress(OSError):
            path.unlink()


def is_send_to_installed() -> bool:
    path = send_to_shortcut_path()
    return bool(path and path.exists())


# -- autostart ------------------------------------------------------------------
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_command() -> str:
    return subprocess.list2cmdline([*launch_command(), "--minimized"])


def _linux_autostart_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / f"{APP_NAME}.desktop"


def _mac_agent_file() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "dk.h4xtor.share.plist"


def is_autostart_enabled() -> bool:
    if _SYSTEM == "Windows":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except OSError:
            return False
    if _SYSTEM == "Darwin":
        return _mac_agent_file().exists()
    return _linux_autostart_file().exists()


def set_autostart(enabled: bool) -> None:
    if _SYSTEM == "Windows":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                with contextlib.suppress(OSError):
                    winreg.DeleteValue(key, APP_NAME)
        return
    if _SYSTEM == "Darwin":
        path = _mac_agent_file()
        if not enabled:
            with contextlib.suppress(OSError):
                path.unlink()
            return
        arguments = "".join(
            f"<string>{part}</string>" for part in [*launch_command(), "--minimized"]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<plist version="1.0"><dict>'
            "<key>Label</key><string>dk.h4xtor.share</string>"
            f"<key>ProgramArguments</key><array>{arguments}</array>"
            "<key>RunAtLoad</key><true/></dict></plist>\n",
            encoding="utf-8",
        )
        return
    path = _linux_autostart_file()
    if not enabled:
        with contextlib.suppress(OSError):
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\nType=Application\nName=h4xtor-share\n"
        f"Exec={_autostart_command()}\nX-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


# -- theme ----------------------------------------------------------------------
def system_prefers_dark() -> bool:
    if _SYSTEM == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
        except OSError:
            return False
    if _SYSTEM == "Darwin":
        try:
            result = subprocess.run(  # noqa: S603
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            return "dark" in result.stdout.lower()
        except (OSError, subprocess.TimeoutExpired):
            return False
    return "dark" in os.environ.get("GTK_THEME", "").lower()


# -- opening links ---------------------------------------------------------------
def find_chrome() -> str | None:
    """Path of Google Chrome, if installed."""
    import shutil

    if _SYSTEM == "Windows":
        candidates = []
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
        try:
            import winreg

            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(
                        root, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
                    ) as key:
                        value, _kind = winreg.QueryValueEx(key, "")
                        candidates.insert(0, Path(value))
                except OSError:
                    continue
        except ImportError:
            pass
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None
    if _SYSTEM == "Darwin":
        app = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        return str(app) if app.exists() else None
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_url(url: str, browser: str = "chrome") -> str:
    """Open *url* in Chrome when preferred and installed, else the default browser.

    Returns which browser was used ("chrome" or "default").
    """
    import webbrowser

    if browser == "chrome":
        chrome = find_chrome()
        if chrome:
            try:
                kwargs: dict[str, Any] = {
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                }
                if _SYSTEM == "Windows":
                    kwargs["creationflags"] = 0x00000008 | 0x00000200  # detached, new group
                else:
                    kwargs["start_new_session"] = True
                subprocess.Popen([chrome, url], **kwargs)  # noqa: S603 - user-approved link
                return "chrome"
            except OSError:
                pass
    webbrowser.open(url)
    return "default"


# -- Explorer right-click menu (Windows) -----------------------------------------
_MENU_KEYS = (
    r"Software\Classes\*\shell\h4xtorshare",
    r"Software\Classes\Directory\shell\h4xtorshare",
)


def is_context_menu_installed() -> bool:
    if _SYSTEM != "Windows":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MENU_KEYS[0]):
            return True
    except OSError:
        return False


def install_context_menu() -> None:
    """Add "Send med h4xtor share" to the right-click menu of files and folders."""
    if _SYSTEM != "Windows":
        raise RuntimeError("The right-click menu is only available on Windows.")
    import winreg

    command = launch_command()
    icon = command[0]
    line = subprocess.list2cmdline([*command, "--send"]) + ' "%1"'
    for key_path in _MENU_KEYS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Send med h4xtor share")
            winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "Send med h4xtor share")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon)
            winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, line)


def remove_context_menu() -> None:
    if _SYSTEM != "Windows":
        return
    import winreg

    for key_path in _MENU_KEYS:
        for path in (key_path + r"\command", key_path):
            with contextlib.suppress(OSError):
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def ensure_shell_integration(config: Any) -> list[str]:
    """First run on Windows: add right-click menu and Send to entry. Returns what was added."""
    added: list[str] = []
    if _SYSTEM != "Windows" or config.get_flag("shell_integration_done", False):
        return added
    with contextlib.suppress(Exception):
        install_context_menu()
        added.append("højreklik-menu")
    with contextlib.suppress(Exception):
        install_send_to()
        added.append("Send til")
    config.set_flag("shell_integration_done", True)
    return added
