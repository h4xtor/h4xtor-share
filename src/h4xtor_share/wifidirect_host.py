"""Make a Wi-Fi Direct network on the PC that a phone can join.

The opposite of :mod:`h4xtor_share.wifidirect` (where the PC joins the phone's
network). Useful when the phone cannot host a group, or when the PC should keep
its normal Wi-Fi/Ethernet while the phone connects straight to it.

* Windows: the WinRT ``WiFiDirectAdvertisementPublisher`` in *legacy* mode, the
  same API as Microsoft's "Wi-Fi Direct legacy AP" sample. It needs a Wi-Fi
  adapter that supports Wi-Fi Direct (most do since Windows 10) and keeps
  running only while a small PowerShell helper lives, so it ends with the app.
* Linux: a NetworkManager hotspot (``nmcli device wifi hotspot``).
* macOS has no API for it; there the PC joins the phone's network instead.

The phone joins with Android's own "connect to device" box (or a Wi-Fi QR code)
and then tells the PC where it is (``POST /api/v1/wifi-direct/joined``).
"""

from __future__ import annotations

import base64
import ipaddress
import os
import platform
import re
import secrets
import subprocess
import threading
import time
from collections.abc import Callable

from h4xtor_share.discovery import local_ipv4_addresses
from h4xtor_share.wifidirect import WifiDirectError

PREFIX = "DIRECT-h4-"
#: Where the PC usually is on its own network: Windows, then NetworkManager.
DEFAULT_ADDRESSES = ("192.168.137.1", "10.42.0.1")
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: easy to type on the phone
_NAME_PART = re.compile(r"[A-Za-z0-9 _-]{1,22}")
_PASSPHRASE = re.compile(r"[\x20-\x7E]{8,63}")
_CREATE_NO_WINDOW = 0x08000000
_NM_CONNECTION = "h4xtor-direct"

#: PowerShell 5.1 helper. Secrets arrive in environment variables, never on the command line.
_WINDOWS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  function Load-WinRT([string]$name, [string[]]$assemblies) {
    foreach ($assembly in $assemblies) {
      $type = [Type]::GetType("$name, $assembly, ContentType=WindowsRuntime")
      if ($type) { return $type }
    }
    throw "WinRT type $name not found"
  }
  $publisherType = Load-WinRT 'Windows.Devices.WiFiDirect.WiFiDirectAdvertisementPublisher' `
    @('Windows.Devices.WiFiDirect', 'Windows.Devices', 'Windows')
  $credentialType = Load-WinRT 'Windows.Security.Credentials.PasswordCredential' `
    @('Windows.Security.Credentials', 'Windows.Security', 'Windows')
  $publisher = [Activator]::CreateInstance($publisherType)
  $ad = $publisher.Advertisement
  $ad.IsAutonomousGroupOwnerEnabled = $true
  $legacy = $ad.LegacySettings
  $legacy.IsEnabled = $true
  $legacy.Ssid = $env:H4X_SSID
  $credential = [Activator]::CreateInstance($credentialType)
  $credential.Password = $env:H4X_PASS
  $legacy.Passphrase = $credential
  if ($env:H4X_PROBE -eq '1') { [Console]::Out.WriteLine('PROBE ok'); exit 0 }
  $publisher.Start()
} catch {
  [Console]::Out.WriteLine('ERROR ' + $_.Exception.Message)
  exit 2
}
$parent = [int]$env:H4X_PARENT
$last = ''
while ($true) {
  $status = [string]$publisher.Status
  if ($status -ne $last) {
    [Console]::Out.WriteLine('STATUS ' + $status); [Console]::Out.Flush(); $last = $status
  }
  if ($status -eq 'Aborted' -or $status -eq 'Stopped') { exit 3 }
  if ($parent -gt 0 -and -not (Get-Process -Id $parent -ErrorAction SilentlyContinue)) {
    $publisher.Stop(); exit 0
  }
  Start-Sleep -Milliseconds 500
}
"""


def default_name(device_name: str) -> str:
    """``DIRECT-h4-`` plus a tidy version of the PC's name (32 bytes at most)."""
    part = re.sub(r"[^A-Za-z0-9 _-]+", "", device_name).strip()[:22]
    return PREFIX + (part or "PC")


def random_passphrase(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def name_error(ssid: str) -> str | None:
    """Why *ssid* cannot be used, or None. It always starts with ``DIRECT-h4-``."""
    if not ssid.startswith(PREFIX):
        return f"Navnet skal starte med {PREFIX}"
    if not _NAME_PART.fullmatch(ssid[len(PREFIX) :]):
        return "Efter DIRECT-h4- højst 22 tegn: a–z, tal, mellemrum, - og _."
    return None


def passphrase_error(passphrase: str) -> str | None:
    if len(passphrase) < 8:
        return "Koden skal være mindst 8 tegn."
    if not _PASSPHRASE.fullmatch(passphrase):
        return "Koden må højst være 63 tegn og kun bruge tegn fra et almindeligt tastatur."
    return None


def wifi_qr_payload(ssid: str, passphrase: str) -> str:
    """The Wi-Fi QR format phone cameras (and h4xtor share's scanner) understand."""

    def escape(value: str) -> str:
        return re.sub(r'([\\;,:"])', r"\\\1", value)

    return f"WIFI:T:WPA;S:{escape(ssid)};P:{escape(passphrase)};;"


def supported() -> str | None:
    """None when this computer can make the network, else why not (in Danish)."""
    system = platform.system()
    if system in ("Windows", "Linux"):
        return None
    return (
        "Mac'en kan ikke lave Wi-Fi Direct. Start det på telefonen og kobl PC'en på dens netværk."
    )


def encoded_script() -> str:
    return base64.b64encode(_WINDOWS_SCRIPT.encode("utf-16-le")).decode("ascii")


def windows_command() -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded_script(),
    ]


def friendly_windows_error(line: str) -> str:
    detail = line.removeprefix("ERROR ").strip()
    lowered = detail.lower()
    if "aborted" in lowered or not detail:
        return (
            "Windows kunne ikke starte Wi-Fi Direct. Tjek at Wi-Fi er slået til, og at "
            "netværkskortet understøtter Wi-Fi Direct (de fleste gør)."
        )
    if "access" in lowered or "denied" in lowered:
        return "Windows afviste Wi-Fi Direct. Tjek at apps må bruge Wi-Fi i Windows' privatliv."
    return f"Wi-Fi Direct kunne ikke starte: {detail}"


class DirectHost:
    """One running network. :meth:`start` blocks until it is up (or raises)."""

    def __init__(self, ssid: str, passphrase: str) -> None:
        problem = name_error(ssid) or passphrase_error(passphrase)
        if problem:
            raise WifiDirectError(problem)
        self.ssid = ssid
        self.passphrase = passphrase
        self.addresses: list[str] = []
        self.started_at = 0.0
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self.on_stopped: Callable[[str], None] | None = None

    @property
    def running(self) -> bool:
        if platform.system() == "Windows":
            return self._process is not None and self._process.poll() is None
        return self.started_at > 0

    def start(self, timeout: float = 25.0) -> list[str]:
        problem = supported()
        if problem:
            raise WifiDirectError(problem)
        before = set(local_ipv4_addresses())
        if platform.system() == "Windows":
            self._start_windows(timeout)
        else:
            self._start_linux()
        self.started_at = time.monotonic()
        self.addresses = self._wait_for_addresses(before, 8.0)
        return self.addresses

    def stop(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            was_running = self.started_at > 0
            self.started_at = 0.0
        if platform.system() == "Windows":
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.kill()
        elif was_running:
            _run(["nmcli", "connection", "down", _NM_CONNECTION], check=False)
            _run(["nmcli", "connection", "delete", _NM_CONNECTION], check=False)

    # ------------------------------------------------------------ Windows
    def _start_windows(self, timeout: float) -> None:
        env = dict(os.environ)
        env.update(H4X_SSID=self.ssid, H4X_PASS=self.passphrase, H4X_PARENT=str(os.getpid()))
        process = subprocess.Popen(  # noqa: S603
            windows_command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            env=env,
            creationflags=_CREATE_NO_WINDOW,
        )
        self._process = process
        lines: list[str] = []
        ready = threading.Event()

        def read() -> None:
            assert process.stdout is not None
            for raw in process.stdout:
                line = raw.strip()
                if not line:
                    continue
                lines.append(line)
                if line == "STATUS Started" or line.startswith("ERROR"):
                    ready.set()
            ready.set()
            if self._process is process and self.on_stopped is not None:
                self.on_stopped(lines[-1] if lines else "")

        threading.Thread(target=read, daemon=True, name="wifi-direct-host").start()
        if not ready.wait(timeout):
            self.stop()
            raise WifiDirectError("Wi-Fi Direct startede ikke inden for tiden. Prøv igen.")
        if "STATUS Started" not in lines:
            self.stop()
            error = next((line for line in lines if line.startswith("ERROR")), "")
            raise WifiDirectError(friendly_windows_error(error or (lines[-1] if lines else "")))

    # -------------------------------------------------------------- Linux
    def _start_linux(self) -> None:
        command = ["nmcli", "device", "wifi", "hotspot", "con-name", _NM_CONNECTION]
        command += ["ssid", self.ssid, "password", self.passphrase]
        try:
            _run(command, timeout=45)
        except WifiDirectError as error:
            raise WifiDirectError(f"NetworkManager kunne ikke lave netværket: {error}") from error

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _wait_for_addresses(before: set[str], seconds: float) -> list[str]:
        """The PC's address on the new network: one that appeared after the start."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            fresh = [address for address in local_ipv4_addresses() if address not in before]
            if fresh:
                return _ordered(fresh)
            time.sleep(0.5)
        return list(DEFAULT_ADDRESSES)


def _ordered(addresses: list[str]) -> list[str]:
    """Private addresses first, the usual defaults after, no duplicates."""
    out: list[str] = []
    for address in [*addresses, *DEFAULT_ADDRESSES]:
        try:
            if ipaddress.ip_address(address).is_loopback:
                continue
        except ValueError:
            continue
        if address not in out:
            out.append(address)
    return out


def _run(command: list[str], timeout: float = 20, check: bool = True) -> str:
    kwargs: dict[str, object] = {"capture_output": True, "text": True, "timeout": timeout}
    if platform.system() == "Windows":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        result = subprocess.run(command, check=False, **kwargs)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as error:
        if check:
            raise WifiDirectError(f"{command[0]}: {error}") from error
        return ""
    if check and result.returncode != 0:
        detail = (result.stdout + result.stderr).strip().splitlines()
        raise WifiDirectError(detail[-1] if detail else f"{command[0]} failed")
    return result.stdout


def probe_windows(timeout: float = 60.0) -> str:
    """Load the WinRT types and build the publisher without starting it (used by tests)."""
    env = dict(os.environ)
    env.update(H4X_SSID=PREFIX + "Test", H4X_PASS="testtest", H4X_PROBE="1", H4X_PARENT="0")
    result = subprocess.run(  # noqa: S603
        windows_command(),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    return (result.stdout + result.stderr).strip()
