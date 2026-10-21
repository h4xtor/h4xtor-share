"""Point the system proxy at Wi-Fi + 5G through a PAC file, and put it back afterwards.

A PAC file (not a fixed proxy) keeps the internet safe: if h4xtor share is closed or
crashes, the PAC address stops answering and browsers simply connect directly.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any

WINDOWS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"{args[0]} failed")
    return result.stdout


def _windows_refresh() -> None:
    import ctypes

    wininet = ctypes.windll.wininet  # type: ignore[attr-defined]
    wininet.InternetSetOptionW(None, 39, None, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
    wininet.InternetSetOptionW(None, 37, None, 0)  # INTERNET_OPTION_REFRESH


def _mac_services() -> list[str]:
    lines = _run("networksetup", "-listallnetworkservices").splitlines()[1:]
    return [line for line in lines if line and not line.startswith("*")]


def apply(pac_url: str) -> dict[str, Any]:
    """Switch the system proxy to the PAC file. Returns what to restore later."""
    system = platform.system()
    if system == "Windows":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, WINDOWS_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            try:
                previous = winreg.QueryValueEx(key, "AutoConfigURL")[0]
            except FileNotFoundError:
                previous = None
            if previous == pac_url:  # left over from a crash: keep the original
                previous = None
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, pac_url)
        _windows_refresh()
        return {"system": system, "url": previous}
    if system == "Darwin":
        saved = {}
        for service in _mac_services():
            info = dict(
                line.split(": ", 1)
                for line in _run("networksetup", "-getautoproxyurl", service).splitlines()
                if ": " in line
            )
            url = "" if info.get("URL") in (None, "(null)") else info["URL"]
            if url != pac_url:
                saved[service] = [url, info.get("Enabled") == "Yes"]
            _run("networksetup", "-setautoproxyurl", service, pac_url)
        return {"system": system, "services": saved}
    if system == "Linux":
        schema = "org.gnome.system.proxy"
        previous_mode = _run("gsettings", "get", schema, "mode").strip().strip("'")
        previous_url = _run("gsettings", "get", schema, "autoconfig-url").strip().strip("'")
        if previous_url == pac_url:
            previous_mode, previous_url = "none", ""
        _run("gsettings", "set", schema, "autoconfig-url", pac_url)
        _run("gsettings", "set", schema, "mode", "auto")
        return {"system": system, "mode": previous_mode, "url": previous_url}
    raise RuntimeError(f"Systemets proxy kan ikke sættes automatisk på {system}.")


def restore(saved: dict[str, Any], pac_url: str) -> None:
    """Undo apply(); leaves settings the user changed meanwhile alone."""
    system = saved.get("system")
    if system == "Windows":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, WINDOWS_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            try:
                current = winreg.QueryValueEx(key, "AutoConfigURL")[0]
            except FileNotFoundError:
                current = None
            if current == pac_url:
                if saved.get("url"):
                    winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, saved["url"])
                else:
                    winreg.DeleteValue(key, "AutoConfigURL")
        _windows_refresh()
    elif system == "Darwin":
        services = saved.get("services", {})
        for service in _mac_services():
            url, enabled = services.get(service, ["", False])
            if url:
                _run("networksetup", "-setautoproxyurl", service, url)
            if not enabled:
                _run("networksetup", "-setautoproxystate", service, "off")
    elif system == "Linux":
        schema = "org.gnome.system.proxy"
        if _run("gsettings", "get", schema, "autoconfig-url").strip().strip("'") == pac_url:
            _run("gsettings", "set", schema, "autoconfig-url", saved.get("url") or "")
            _run("gsettings", "set", schema, "mode", saved.get("mode") or "none")
