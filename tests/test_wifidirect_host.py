"""Wi-Fi Direct made by the PC: names, codes, the helpers per OS and the protocol."""

from __future__ import annotations

import base64
import io
import platform
import subprocess
from pathlib import Path

import pytest
from test_core_v12 import PHONE_CAPS, desktop, last, phone, post  # noqa: F401

from h4xtor_share import wifidirect_host
from h4xtor_share.models import DESKTOP_CAPABILITIES, Peer, WifiDirectJoined
from h4xtor_share.wifidirect import WifiDirectError


def test_names_codes_and_qr() -> None:
    assert wifidirect_host.default_name("AdminPC") == "DIRECT-h4-AdminPC"
    assert wifidirect_host.default_name("Lennarts PC (hjem)!") == "DIRECT-h4-Lennarts PC hjem"
    assert wifidirect_host.default_name("ææø") == "DIRECT-h4-PC"
    assert len(wifidirect_host.default_name("x" * 80)) <= 32
    code = wifidirect_host.random_passphrase()
    assert len(code) == 8
    assert not set(code) & set("01ilo")
    assert wifidirect_host.name_error("DIRECT-h4-AdminPC") is None
    assert wifidirect_host.name_error("Mit netværk") is not None
    assert wifidirect_host.name_error("DIRECT-h4-" + "x" * 23) is not None
    assert wifidirect_host.passphrase_error("hemmelig") is None
    assert wifidirect_host.passphrase_error("kort") is not None
    assert wifidirect_host.passphrase_error("blåbærgrød") is not None
    assert (
        wifidirect_host.wifi_qr_payload("DIRECT-h4-PC", "a;b:c\\d,e")
        == "WIFI:T:WPA;S:DIRECT-h4-PC;P:a\\;b\\:c\\\\d\\,e;;"
    )
    with pytest.raises(WifiDirectError):
        wifidirect_host.DirectHost("Forkert navn", "hemmelig")
    with pytest.raises(WifiDirectError):
        wifidirect_host.DirectHost("DIRECT-h4-PC", "kort")


def test_windows_helper_keeps_secrets_off_the_command_line() -> None:
    command = wifidirect_host.windows_command()
    assert command[0] == "powershell.exe"
    script = base64.b64decode(command[-1]).decode("utf-16-le")
    assert "WiFiDirectAdvertisementPublisher" in script
    assert "LegacySettings" in script
    assert "$env:H4X_PASS" in script
    assert "hemmelig" not in " ".join(command)


def test_friendly_errors() -> None:
    assert "Wi-Fi" in wifidirect_host.friendly_windows_error("STATUS Aborted")
    assert "afviste" in wifidirect_host.friendly_windows_error("ERROR Access is denied.")
    assert "kunne ikke starte: boom" in wifidirect_host.friendly_windows_error("ERROR boom")


class _FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = io.StringIO("".join(f"{line}\n" for line in lines))
        self.terminated = False
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.terminated = True
        self.code = 0

    def wait(self, _timeout: float) -> int:
        return 0

    def kill(self) -> None:
        self.code = -9


def _windows(monkeypatch, lines: list[str]) -> list[_FakeProcess]:
    made: list[_FakeProcess] = []

    def popen(command, **kwargs):
        assert kwargs["env"]["H4X_SSID"] == "DIRECT-h4-PC"
        assert kwargs["env"]["H4X_PASS"] == "hemmelig"
        process = _FakeProcess(lines)
        made.append(process)
        return process

    monkeypatch.setattr(wifidirect_host.platform, "system", lambda: "Windows")
    monkeypatch.setattr(wifidirect_host.subprocess, "Popen", popen)
    after = ["192.168.1.20", "192.168.137.1"]
    calls = iter([["192.168.1.20"], after])
    monkeypatch.setattr(wifidirect_host, "local_ipv4_addresses", lambda: next(calls, after))
    return made


def test_windows_start_reads_the_status_and_finds_the_new_address(monkeypatch) -> None:
    made = _windows(monkeypatch, ["STATUS Created", "STATUS Started"])
    host = wifidirect_host.DirectHost("DIRECT-h4-PC", "hemmelig")
    assert host.start(timeout=5) == ["192.168.137.1", "10.42.0.1"]
    host.stop()
    assert made[0].terminated


def test_windows_start_failure_is_explained(monkeypatch) -> None:
    _windows(monkeypatch, ["ERROR Access is denied."])
    host = wifidirect_host.DirectHost("DIRECT-h4-PC", "hemmelig")
    with pytest.raises(WifiDirectError, match="afviste"):
        host.start(timeout=5)
    assert not host.running


def test_linux_uses_a_networkmanager_hotspot(monkeypatch) -> None:
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wifidirect_host.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wifidirect_host.subprocess, "run", run)
    monkeypatch.setattr(wifidirect_host, "local_ipv4_addresses", lambda: ["192.168.1.5"])
    monkeypatch.setattr(
        wifidirect_host.DirectHost, "_wait_for_addresses", lambda *_a: ["10.42.0.1"]
    )
    host = wifidirect_host.DirectHost("DIRECT-h4-PC", "hemmelig")
    assert host.start() == ["10.42.0.1"]
    assert host.running
    assert commands[0][:4] == ["nmcli", "device", "wifi", "hotspot"]
    assert commands[0][-4:] == ["ssid", "DIRECT-h4-PC", "password", "hemmelig"]
    host.stop()
    assert ["nmcli", "connection", "down", "h4xtor-direct"] in commands
    assert not host.running


def test_mac_explains_that_it_cannot(monkeypatch) -> None:
    monkeypatch.setattr(wifidirect_host.platform, "system", lambda: "Darwin")
    assert "Mac" in (wifidirect_host.supported() or "")
    with pytest.raises(WifiDirectError, match="Mac"):
        wifidirect_host.DirectHost("DIRECT-h4-PC", "hemmelig").start()


@pytest.mark.skipif(platform.system() != "Windows", reason="WinRT only exists on Windows")
def test_windows_winrt_types_load() -> None:
    # Builds the real publisher (without starting it): proves the WinRT names resolve.
    assert "PROBE ok" in wifidirect_host.probe_windows()


# -- protocol -------------------------------------------------------------------
def test_desktop_advertises_it() -> None:
    assert "wifi-direct-pc" in DESKTOP_CAPABILITIES


async def test_phone_announces_that_it_joined(desktop) -> None:  # noqa: F811
    config, events = desktop
    status, body = await post(config, "/api/v1/wifi-direct/joined", {"port": 47474, "ssid": "D"})
    assert status == 200, body
    event = events[-1]
    assert isinstance(event, WifiDirectJoined)
    assert event.address == "127.0.0.1"
    assert event.port == 47474
    assert (await post(config, "/api/v1/wifi-direct/joined", {"port": 70000}))[0] == 400
    assert (await post(config, "/api/v1/wifi-direct/joined", {}, auth=False))[0] == 401


async def test_client_offers_the_network_to_a_phone(phone, tmp_path: Path) -> None:  # noqa: F811
    fake, client, peer = phone
    able = Peer(
        peer.device_id, peer.name, peer.address, peer.port, peer.fingerprint, "android",
        capabilities=(*PHONE_CAPS, "wifi-direct-pc"),
    )
    addresses = [f"10.0.0.{index}" for index in range(12)]
    await client.offer_pc_wifi_direct(able, "DIRECT-h4-PC", "hemmelig", addresses)
    method, path, _headers, body = last(fake)
    assert (method, path) == ("POST", "/api/v1/wifi-direct/pc-offer")
    assert body == {"ssid": "DIRECT-h4-PC", "passphrase": "hemmelig", "addresses": addresses[:8]}
    with pytest.raises(RuntimeError, match="Telefonen skal opdateres"):
        await client.offer_pc_wifi_direct(peer, "DIRECT-h4-PC", "hemmelig", [])
