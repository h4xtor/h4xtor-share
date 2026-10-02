"""Join an Android Wi-Fi Direct group from the desktop.

Android can create a Wi-Fi Direct (P2P) group with a known network name and
passphrase. Any Wi-Fi capable computer can join that group as a *legacy
client*, exactly like a normal WPA2 network, without a router or internet
connection. The group owner (the phone) is always ``192.168.49.1``.

Windows uses ``netsh wlan`` with a temporary WPA2-PSK profile, Linux uses
NetworkManager (``nmcli``) and macOS uses ``networksetup``.
"""

from __future__ import annotations

import ipaddress
import platform
import re
import subprocess
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

from h4xtor_share.discovery import local_ipv4_addresses

ANDROID_GROUP_OWNER = "192.168.49.1"
ANDROID_P2P_NETWORK = ipaddress.ip_network("192.168.49.0/24")
_CREATE_NO_WINDOW = 0x08000000


class WifiDirectError(RuntimeError):
    pass


def windows_profile_xml(ssid: str, passphrase: str) -> str:
    name = escape(ssid)
    key = escape(passphrase)
    return f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{name}</name>
  <SSIDConfig>
    <SSID>
      <name>{name}</name>
    </SSID>
  </SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>manual</connectionMode>
  <MSM>
    <security>
      <authEncryption>
        <authentication>WPA2PSK</authentication>
        <encryption>AES</encryption>
        <useOneX>false</useOneX>
      </authEncryption>
      <sharedKey>
        <keyType>passPhrase</keyType>
        <protected>false</protected>
        <keyMaterial>{key}</keyMaterial>
      </sharedKey>
    </security>
  </MSM>
</WLANProfile>
"""


def _run(command: list[str], timeout: float = 20) -> str:
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        result = subprocess.run(command, check=False, **kwargs)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WifiDirectError(f"{command[0]} failed: {error}") from error
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip().splitlines()
        raise WifiDirectError(detail[-1] if detail else f"{command[0]} failed")
    return result.stdout


def current_wifi_ssid() -> str | None:
    """Best-effort name of the Wi-Fi network this computer is connected to."""
    system = platform.system()
    try:
        if system == "Windows":
            output = _run(["netsh", "wlan", "show", "interfaces"], timeout=8)
            match = re.search(r"^\s*SSID\s*:\s*(.+)$", output, re.MULTILINE)
            return match.group(1).strip() if match else None
        if system == "Linux":
            output = _run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], timeout=8)
            for line in output.splitlines():
                if line.startswith("yes:"):
                    return line.split(":", 1)[1] or None
        if system == "Darwin":
            device = _mac_wifi_device()
            output = _run(["networksetup", "-getairportnetwork", device], timeout=8)
            if ":" in output:
                return output.split(":", 1)[1].strip() or None
    except WifiDirectError:
        return None
    return None


def _mac_wifi_device() -> str:
    output = _run(["networksetup", "-listallhardwareports"], timeout=8)
    blocks = output.split("\n\n")
    for block in blocks:
        if "Wi-Fi" in block or "AirPort" in block:
            match = re.search(r"Device:\s*(\S+)", block)
            if match:
                return match.group(1)
    return "en0"


def join_network(ssid: str, passphrase: str) -> None:
    """Connect this computer's Wi-Fi adapter to *ssid* (WPA2-PSK)."""
    if not ssid or len(ssid) > 32:
        raise WifiDirectError("Invalid network name.")
    if not 8 <= len(passphrase) <= 63:
        raise WifiDirectError("Invalid Wi-Fi Direct password.")
    system = platform.system()
    if system == "Windows":
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "h4xtor-wifi-direct.xml"
            profile.write_text(windows_profile_xml(ssid, passphrase), encoding="utf-8")
            _run(["netsh", "wlan", "add", "profile", f"filename={profile}", "user=current"])
        _run(["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"])
    elif system == "Linux":
        _run(["nmcli", "device", "wifi", "connect", ssid, "password", passphrase], timeout=45)
    elif system == "Darwin":
        _run(["networksetup", "-setairportnetwork", _mac_wifi_device(), ssid, passphrase], 45)
    else:
        raise WifiDirectError(f"Wi-Fi Direct join is not supported on {system}.")


def reconnect(ssid: str) -> None:
    """Switch back to a previously used Wi-Fi network."""
    system = platform.system()
    if system == "Windows":
        _run(["netsh", "wlan", "connect", f"name={ssid}"])
    elif system == "Linux":
        _run(["nmcli", "connection", "up", "id", ssid], timeout=45)
    elif system == "Darwin":
        _run(["networksetup", "-setairportnetwork", _mac_wifi_device(), ssid], 45)


def p2p_address() -> str | None:
    for address in local_ipv4_addresses():
        try:
            if ipaddress.ip_address(address) in ANDROID_P2P_NETWORK:
                return address
        except ValueError:
            continue
    return None


def wait_for_p2p_address(timeout_seconds: float = 30.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        address = p2p_address()
        if address:
            return address
        time.sleep(0.5)
    raise WifiDirectError(
        "Joined the network, but no Wi-Fi Direct address arrived. "
        "Check that the phone still shows the Wi-Fi Direct group."
    )


def connect_to_group(ssid: str, passphrase: str, timeout_seconds: float = 30.0) -> str:
    """Join the group and wait for a 192.168.49.x address. Returns it."""
    if p2p_address() and current_wifi_ssid() == ssid:
        return p2p_address() or ""
    join_network(ssid, passphrase)
    return wait_for_p2p_address(timeout_seconds)
