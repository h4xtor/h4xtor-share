from __future__ import annotations

import platform

import pytest

from h4xtor_share import sysproxy

PAC = "http://127.0.0.1:47480/proxy.pac"


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows registry")
def test_windows_registry_round_trip() -> None:
    import winreg

    def current() -> str | None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sysproxy.WINDOWS_KEY) as key:
            try:
                return winreg.QueryValueEx(key, "AutoConfigURL")[0]
            except FileNotFoundError:
                return None

    before = current()
    saved = sysproxy.apply(PAC)
    try:
        assert current() == PAC
    finally:
        sysproxy.restore(saved, PAC)
    assert current() == before


def test_linux_gnome_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = {"mode": "'none'", "autoconfig-url": "''"}

    def fake_run(*args: str) -> str:
        assert args[0] == "gsettings"
        if args[1] == "get":
            return settings[args[3]] + "\n"
        settings[args[3]] = f"'{args[4]}'"
        return ""

    monkeypatch.setattr(sysproxy.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sysproxy, "_run", fake_run)
    saved = sysproxy.apply(PAC)
    assert settings == {"mode": "'auto'", "autoconfig-url": f"'{PAC}'"}
    sysproxy.restore(saved, PAC)
    assert settings == {"mode": "'none'", "autoconfig-url": "''"}


def test_mac_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"Wi-Fi": ["", False], "USB": ["http://corp/pac", True]}
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str) -> str:
        calls.append(args)
        if args[1] == "-listallnetworkservices":
            return "An asterisk (*) denotes that a network service is disabled.\nWi-Fi\nUSB\n*Off\n"
        if args[1] == "-getautoproxyurl":
            url, enabled = state[args[2]]
            return f"URL: {url or '(null)'}\nEnabled: {'Yes' if enabled else 'No'}\n"
        if args[1] == "-setautoproxyurl":
            state[args[2]] = [args[3], True]
        elif args[1] == "-setautoproxystate":
            state[args[2]][1] = args[3] == "on"
        return ""

    monkeypatch.setattr(sysproxy.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(sysproxy, "_run", fake_run)
    saved = sysproxy.apply(PAC)
    assert state == {"Wi-Fi": [PAC, True], "USB": [PAC, True]}
    assert not any("*Off" in call for call in calls)
    sysproxy.restore(saved, PAC)
    assert state["USB"] == ["http://corp/pac", True]
    assert state["Wi-Fi"][1] is False
