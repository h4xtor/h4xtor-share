"""End-to-end: the real Android app (in an emulator) against the real desktop core.

Runs inside reactivecircus/android-emulator-runner in CI. The host is reachable
from the emulator as 10.0.2.2; the phone's server is reached through
``adb forward``. Screenshots of every screen are written to ``$E2E_SHOTS``.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from h4xtor_share.client import PeerClient  # noqa: E402
from h4xtor_share.config import Config  # noqa: E402
from h4xtor_share.crypto import ensure_certificate, server_ssl_context  # noqa: E402
from h4xtor_share.models import (  # noqa: E402
    ClipboardReceived,
    FileReceived,
    FolderReceived,
    LinkReceived,
    Peer,
    PeerPaired,
)
from h4xtor_share.pairing import PairingInvite  # noqa: E402
from h4xtor_share.server import ShareServer  # noqa: E402

PKG = "com.h4xtor.share"
APK = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
SHOTS = Path(os.environ.get("E2E_SHOTS", "e2e-shots"))
SHOTS.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix="h4x-android-e2e-"))
RESULTS: list[str] = []


def adb(*args: str, check: bool = True, timeout: float = 60) -> str:
    result = subprocess.run(
        ["adb", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)} failed: {result.stderr or result.stdout}")
    return result.stdout


def shell(command: str, check: bool = True) -> str:
    return adb("shell", command, check=check)


def shot(name: str) -> None:
    time.sleep(1.2)
    data = subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True,
                          timeout=30, check=True).stdout
    (SHOTS / f"{name}.png").write_bytes(data)


def _dump() -> list[ET.Element]:
    shell("uiautomator dump /sdcard/ui.xml", check=False)
    xml = adb("exec-out", "cat", "/sdcard/ui.xml", check=False)
    try:
        return list(ET.fromstring(xml).iter("node"))
    except ET.ParseError:
        return []


def ui_nodes() -> list[ET.Element]:
    """Current screen, after dismissing emulator 'X isn't responding' dialogs (not our app)."""
    nodes = _dump()
    if any("isn't responding" in (n.get("text") or "") for n in nodes):
        for node in nodes:
            if (node.get("text") or "") == "Wait":
                x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds", "")))
                shell(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")
                time.sleep(1)
                return _dump()
    return nodes


def tap_text(pattern: str, timeout: float = 15) -> None:
    deadline = time.time() + timeout
    regex = re.compile(pattern)
    while time.time() < deadline:
        # Last match wins: bottom navigation sits below any same-named page header.
        for node in reversed(ui_nodes()):
            if regex.search(node.get("text") or "") or regex.search(node.get("content-desc") or ""):
                x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds", "")))
                shell(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")
                return
        time.sleep(1)
    raise AssertionError(f"no element matching {pattern!r} on screen")


def scroll_to(pattern: str, swipes: int = 10) -> bool:
    """Scroll down to find *pattern*; if it is not below, scroll back up."""
    regex = re.compile(pattern)
    for direction in ("540 1700 540 700", "540 700 540 1700"):
        for _ in range(swipes):
            if any(regex.search(n.get("text") or "") for n in ui_nodes()):
                return True
            shell(f"input swipe {direction} 400")
            time.sleep(0.8)
    return False


def screen_has(pattern: str, timeout: float = 15) -> bool:
    deadline = time.time() + timeout
    regex = re.compile(pattern)
    while time.time() < deadline:
        if any(regex.search(n.get("text") or "") for n in ui_nodes()):
            return True
        time.sleep(1)
    return False


def ok(message: str) -> None:
    RESULTS.append(message)
    print("OK", message, flush=True)


class Desktop:
    def __init__(self, name: str = "AdminPC", port: int = 47474) -> None:
        self.name = name
        self.port = port
        self.config = Config(WORK / name / "config.json")
        self.config.data.update(
            device_name=name, port=port, platform="windows",
            incoming_directory=str(WORK / f"{name}-in"),
        )
        self.config.save()
        cert, key, self.fp = ensure_certificate(self.config.path.parent, name)
        self.events: list[object] = []
        self.server = ShareServer(self.config, server_ssl_context(cert, key), self.fp,
                                  self.events.append, host="0.0.0.0")
        self.client = PeerClient(self.config, fingerprint=self.fp)
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.run(self.server.start())

    def run(self, coroutine, timeout: float = 60):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    def wait_for(self, kind: type, timeout: float = 45.0, match=None):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for event in list(self.events):
                if isinstance(event, kind) and (match is None or match(event)):
                    self.events.remove(event)
                    return event
            time.sleep(0.2)
        raise AssertionError(f"desktop never received {kind.__name__}")


def prefs() -> str:
    return shell(f"run-as {PKG} cat shared_prefs/h4xtor_share.xml", check=False)


def main() -> None:
    adb("wait-for-device")
    adb("install", "-r", "-g", str(APK), timeout=240)
    for permission in ("POST_NOTIFICATIONS", "NEARBY_WIFI_DEVICES"):
        shell(f"pm grant {PKG} android.permission.{permission}", check=False)
    shell("settings put global window_animation_scale 0", check=False)
    shell("settings put global transition_animation_scale 0", check=False)
    shell("settings put global animator_duration_scale 0", check=False)
    shell("cmd uimode night no", check=False)

    desktop = Desktop()
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(6)
    shot("01-first-start")

    # ---- Pair by "scanning" the desktop QR code (deep link) -----------------
    invite = PairingInvite(desktop.config.device_id, "AdminPC", desktop.fp, 47474, ("10.0.2.2",),
                           desktop.server.create_qr_secret(), "windows")
    shell(f"am start -W -a android.intent.action.VIEW -d '{invite.to_uri()}' {PKG}")
    paired: PeerPaired = desktop.wait_for(PeerPaired)
    assert desktop.config.is_trusted(paired.peer.device_id)
    ok("QR pairing (phone -> PC) and mutual trust")
    adb("forward", "tcp:47475", "tcp:47474")
    phone = Peer(paired.peer.device_id, paired.peer.name, "127.0.0.1", 47475,
                 paired.peer.fingerprint, "android", "lan", paired.peer.capabilities)
    assert screen_has("AdminPC", 20), "PC not shown on phone after pairing"
    time.sleep(5)
    shot("02-home-paired")
    ok("phone shows the paired PC")

    # ---- PC -> phone ----------------------------------------------------------
    desktop.run(desktop.client.send_clipboard(phone, "Hej fra PC'en"))
    time.sleep(2)
    assert "Hej fra PC" in prefs(), "clipboard text not recorded on phone"
    ok("clipboard PC -> phone")

    payload = WORK / "ferie.jpg"
    payload.write_bytes(os.urandom(3 * 1024 * 1024))
    desktop.run(desktop.client.send_file(phone, payload, lambda _p: None), timeout=120)
    time.sleep(2)
    listing = shell("ls -l /sdcard/Download/h4xtor-share/", check=False)
    assert "ferie.jpg" in listing, listing
    assert str(payload.stat().st_size) in listing, listing
    ok("3 MB file PC -> phone lands in Downloads/h4xtor-share")

    folder = WORK / "Projekt"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text("a")
    (folder / "sub" / "b.txt").write_text("b" * 5000)
    desktop.run(desktop.client.send_folder(phone, folder, lambda _p: None), timeout=120)
    time.sleep(2)
    listing = shell("ls -R /sdcard/Download/h4xtor-share/Projekt", check=False)
    assert "a.txt" in listing and "b.txt" in listing, listing
    ok("folder with subfolder PC -> phone")

    desktop.run(desktop.client.send_link(phone, "https://example.com/fra-pc"))
    time.sleep(3)
    assert "fra-pc" in prefs()
    ok("link PC -> phone")
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(2)

    # ---- Phone -> PC via the Android share sheet ------------------------------
    shell(
        "am start -W -a android.intent.action.SEND -t text/plain "
        "--es android.intent.extra.TEXT 'https://example.com/fra-telefon' "
        f"-n {PKG}/.ShareTargetActivity"
    )
    desktop.wait_for(LinkReceived, match=lambda event: event.url == "https://example.com/fra-telefon")
    ok("share sheet link phone -> PC (opens in Chrome on the PC)")

    shell(
        "am start -W -a android.intent.action.PROCESS_TEXT -t text/plain "
        "--es android.intent.extra.PROCESS_TEXT 'markeret tekst' "
        f"-n {PKG}/.ShareTargetActivity"
    )
    # The phone may also sync its own clipboard when it gains focus: wait for ours.
    desktop.wait_for(ClipboardReceived, match=lambda event: event.text == "markeret tekst")
    ok("'Send til PC' from the text selection menu")

    # ---- Phone -> PC instantly: tap "Copy" in another app ---------------------
    service = f"{PKG}/{PKG}.CopyWatchService"
    shell(f"settings put secure enabled_accessibility_services {service}")
    shell("settings put secure accessibility_enabled 1")
    time.sleep(3)
    bound = shell("dumpsys accessibility", check=False)
    assert "CopyWatchService" in bound, "copy watcher not bound"
    word = "telefonkopi"
    shell("am start -W -a android.intent.action.INSERT -t vnd.android.cursor.dir/contact "
          f"-e name {word}")
    time.sleep(4)
    field = None
    for _ in range(10):
        field = next((n for n in ui_nodes() if (n.get("text") or "") == word), None)
        if field is not None:
            break
        time.sleep(1)
    shot("14-copy-other-app")
    assert field is not None, "contact editor with the test text did not open"
    x1, y1, x2, y2 = map(int, re.findall(r"\d+", field.get("bounds")))
    desktop.events.clear()
    shell(f"input swipe {(x1 + x2) // 2} {(y1 + y2) // 2} {(x1 + x2) // 2} {(y1 + y2) // 2} 900")
    time.sleep(1.5)
    shot("15-long-press")
    # The text toolbar is a popup that `uiautomator dump` cannot see, so tap it by position
    # (pixel_7 profile): it floats 40 px above the field, centred on the cursor/selection.
    shell(f"input tap {x1 + 248} {y1 - 40}")  # "Select all"
    time.sleep(1.5)
    shot("16-selected")
    shell(f"input tap {x1 + 381} {y1 - 40}")  # "Copy" (Translate | Cut | Copy | Paste | ⋮)
    time.sleep(1.5)
    shot("17-copied")
    desktop.wait_for(ClipboardReceived, timeout=20, match=lambda event: event.text == word)
    ok("tap 'Copy' in another app -> text on the PC instantly (app in background)")
    shell("input keyevent BACK", check=False)
    shell("input keyevent BACK", check=False)

    # Phone -> PC file through the share sheet. The file the phone received above
    # is owned by the app in MediaStore, so the app may read it like a file shared
    # from the gallery or the Files app (which grant read access to the content:// uri).
    uri = ""
    for _ in range(15):
        out = shell("content query --uri content://media/external/downloads --projection _id "
                    "--where \"_display_name='ferie.jpg'\"", check=False)
        match = re.search(r"_id=(\d+)", out)
        if match:
            uri = f"content://media/external/downloads/{match.group(1)}"
            break
        time.sleep(1)
    assert uri, "received file is not in MediaStore"
    desktop.events.clear()
    shell("am start -W -a android.intent.action.SEND -t image/jpeg "
          f"--eu android.intent.extra.STREAM {uri} -n {PKG}/.ShareTargetActivity")
    shot("11-share-progress")
    received: FileReceived = desktop.wait_for(FileReceived, timeout=90)
    assert received.path.name.startswith("ferie"), received.path
    assert received.path.read_bytes() == payload.read_bytes(), "file changed on the way"
    ok("share sheet file phone -> PC (3 MB, byte-identical)")

    # ---- A second PC: the share sheet now asks where to send ----------------
    laptop = Desktop("Bærbar", 47478)
    invite2 = PairingInvite(laptop.config.device_id, "Bærbar", laptop.fp, 47478, ("10.0.2.2",),
                            laptop.server.create_qr_secret(), "windows")
    shell(f"am start -W -a android.intent.action.VIEW -d '{invite2.to_uri()}' {PKG}")
    laptop.wait_for(PeerPaired)
    ok("second PC paired")
    time.sleep(4)
    desktop.events.clear()
    shell("am start -W -a android.intent.action.SEND -t text/plain "
          "--es android.intent.extra.TEXT 'https://example.com/valgt' "
          f"-n {PKG}/.ShareTargetActivity")
    assert screen_has("Bærbar", 15) and screen_has("AdminPC", 5), "sheet does not list both PCs"
    shot("09-share-sheet")
    tap_text("^AdminPC$")
    desktop.wait_for(LinkReceived, match=lambda event: event.url == "https://example.com/valgt")
    ok("share sheet with two PCs: pick AdminPC, link arrives there")

    # ---- Folder phone -> PC through the system folder picker -----------------
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(3)
    desktop.events.clear()
    tap_text("^Mappe$")
    time.sleep(3)
    shot("10-folder-picker")
    for _ in range(8):
        texts = " ".join(n.get("text") or "" for n in ui_nodes())
        if "a.txt" in texts:  # inside Projekt
            break
        for name in ("^Projekt$", "^h4xtor-share$", "^Download$", "^Downloads$"):
            if any(re.search(name, n.get("text") or "") for n in ui_nodes()):
                tap_text(name)
                break
        time.sleep(2)
    tap_text("(?i)^use this folder$")
    time.sleep(1.5)
    tap_text("(?i)^allow$")
    folder_event: FolderReceived = desktop.wait_for(FolderReceived, timeout=90)
    got = folder_event.path
    assert (got / "a.txt").read_text() == "a", list(got.rglob("*"))
    assert (got / "sub" / "b.txt").read_text() == "b" * 5000
    ok("folder phone -> PC via the system picker (subfolders intact)")

    # ---- Nerd panel: speed test against the PC ------------------------------
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(2)
    tap_text("^Indstillinger$")
    assert scroll_to("^Test hastighed til PC$"), "speed test button missing"
    shot("12-nerd-panel")
    tap_text("^Test hastighed til PC$")
    assert screen_has(r"^Upload .* ping \d+ ms$", 60), "speed test gave no result"
    shot("13-speedtest-result")
    ok("speed test phone -> PC (upload + ping shown)")

    # ---- Trick: new screenshots are sent to the PC automatically ------------
    assert scroll_to("^Send nye skærmbilleder til PC'en$"), "screenshot trick missing"
    tap_text("^Send nye skærmbilleder til PC'en$")
    time.sleep(2)
    for node in (desktop, laptop):
        node.events.clear()
    shell("mkdir -p /sdcard/Pictures/Screenshots")
    shell("screencap -p /sdcard/Pictures/Screenshots/Screenshot_e2e.png")
    shell("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
          "-d file:///sdcard/Pictures/Screenshots/Screenshot_e2e.png", check=False)
    deadline = time.time() + 60
    got_shot = None
    while time.time() < deadline and got_shot is None:
        for node in (desktop, laptop):
            for event in list(node.events):
                if isinstance(event, FileReceived) and event.path.name.startswith("Screenshot_e2e"):
                    got_shot = event
        time.sleep(0.5)
    assert got_shot is not None, "new screenshot was not sent to the PC"
    ok("new screenshot sent to the PC automatically")

    # ---- Screens for design review ---------------------------------------------
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(3)
    shot("03-home")
    tap_text("^Overførsler$")
    shot("04-transfers")
    time.sleep(1)
    opens = [n for n in ui_nodes() if (n.get("text") or "") == "Åbn"]
    assert len(opens) >= 2, f"sent files need an Åbn button too (found {len(opens)})"
    ok("Åbn on both received and sent files in Overførsler")
    tap_text("^Historik$")
    shot("05-history")
    tap_text("^Indstillinger$")
    shot("06-settings")
    tap_text("^Del$")
    shell("am start -W -a android.intent.action.SEND -t text/plain "
          "--es android.intent.extra.TEXT 'https://example.com' "
          f"-n {PKG}/.ShareTargetActivity", check=False)
    time.sleep(1)
    shell("cmd uimode night yes", check=False)
    shell(f"am force-stop {PKG}", check=False)
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(6)
    shot("07-home-dark")
    tap_text("^Overførsler$")
    shot("08-transfers-dark")

    # ---- Unpair from the PC -> phone forgets it too ---------------------------
    desktop.run(desktop.client.unpair(phone))
    time.sleep(3)
    assert f"out_token_{desktop.config.device_id}" not in prefs(), "phone kept the pairing"
    ok("unpair from PC removes the pairing on the phone too")
    (SHOTS / "results.txt").write_text("\n".join(RESULTS) + "\n", encoding="utf-8")
    print("ALL ANDROID E2E CHECKS PASSED", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            shot("99-final")
            pid = shell(f"pidof {PKG}", check=False).strip()
            args = ["adb", "logcat", "-d", "-t", "3000"] + ([f"--pid={pid}"] if pid else ["*:E"])
            with open(SHOTS / "logcat.txt", "w", encoding="utf-8") as log:
                subprocess.run(args, stdout=log, timeout=30, check=False)
        except Exception:  # noqa: BLE001
            pass
