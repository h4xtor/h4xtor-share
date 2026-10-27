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
    NotificationReceived,
    NotificationRemoved,
    Peer,
    PeerPaired,
    SmsReceived,
)
from h4xtor_share.netmerge import NetMerge  # noqa: E402
from h4xtor_share.pairing import PairingInvite  # noqa: E402
from h4xtor_share.server import ShareServer  # noqa: E402

PKG = "com.h4xtor.share"
APK = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
# The same app built as an older version (CI: -Ph4xVersionCode/-Ph4xVersionName) to update from.
OLD_APK = ROOT / "android/app/build/outputs/apk/debug/app-old.apk"
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


def quick_shot(name: str) -> None:
    """A screenshot right away (shot() waits for the screen to settle; gestures do not)."""
    data = subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True,
                          timeout=30, check=True).stdout
    (SHOTS / f"{name}.png").write_bytes(data)


def mascot_checks() -> None:
    """The Del page's Battle.net hero with the monkey; a tap on the monkey makes it grin.

    The rest of the run keeps Android's animations off for stable taps, so they are switched
    on just for this, and the grin is caught by quick screenshots while it holds open.
    """
    shell("settings put global animator_duration_scale 1", check=False)
    try:
        tap_text("^Del$")
        time.sleep(2)
        assert screen_has("^SEND FILER$", 10), "the hero's big send button is missing"
        # 10 s, not 2: a UI dump taken while the live status rebuilds the page sees nothing.
        assert screen_has("^SEND TIL$", 10), "the hero does not say who it sends to"
        quick_shot("40-hero")
        tap_text("tryk for at hilse")  # the monkey's description
        for index in range(3):
            quick_shot(f"41-monkey-grin-{index}")
        time.sleep(1.5)
        quick_shot("42-monkey-after")
    finally:
        shell("settings put global animator_duration_scale 0", check=False)
    ok("Del page: Battle.net hero with SEND FILER; a tap on the monkey makes it grin")


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


def open_settings_row(pattern: str) -> None:
    """Open Indstillinger and tap the row matching *pattern* (scrolling to it)."""
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(2)
    for _ in range(3):
        tap_text("^Indstillinger$")
        time.sleep(1)
        if scroll_to(pattern):
            break
    else:
        raise AssertionError(f"settings row {pattern!r} missing")
    tap_text(pattern)
    time.sleep(2)


def v12_checks(desktop: Desktop, phone: Peer) -> None:
    """v1.2 (Join parity): notifications, SMS, find phone, remote control, screenshot."""
    for capability in ("notifications", "sms", "screenshot-request", "find-phone",
                       "remote-control"):
        assert phone.supports(capability), f"phone does not advertise {capability}"

    # ---- Notifications are off by default: the phone refuses actions ----------
    try:
        desktop.run(desktop.client.notification_action(phone, "x", "dismiss"))
        raise AssertionError("notification action accepted while mirroring is off")
    except RuntimeError as error:
        assert "slået fra" in str(error), error
    ok("notification mirroring is off by default")

    # ---- Phone notification -> PC, then dismissed from the PC -----------------
    open_settings_row("^Vis telefonens notifikationer på PC'en$")
    shot("20-notification-access")
    shell("input keyevent BACK", check=False)  # leave Android's access screen
    shell(f"cmd notification allow_listener {PKG}/{PKG}.NotificationMirrorService")
    time.sleep(4)
    assert "flag_mirror_notifications\" value=\"true" in prefs(), "mirror toggle not saved"
    desktop.events.clear()
    shell("cmd notification post -S bigtext -t Mor e2e-tag 'Kommer du til middag?'")
    note = desktop.wait_for(NotificationReceived, timeout=45,
                            match=lambda event: event.title == "Mor")
    assert "middag" in note.text, note
    assert note.can_dismiss, note
    ok("phone notification shows up on the PC (title, text, app)")
    desktop.run(desktop.client.notification_action(phone, note.key, "dismiss"))
    desktop.wait_for(NotificationRemoved, timeout=20, match=lambda event: event.key == note.key)
    ok("notification dismissed from the PC disappears on the phone")

    # ---- SMS in the emulator ---------------------------------------------------
    open_settings_row("^SMS fra PC'en$")  # permissions were granted at install (-g)
    time.sleep(2)
    assert "flag_sms_enabled\" value=\"true" in prefs(), "SMS toggle not saved"
    shot("21-sms-enabled")
    desktop.events.clear()
    # The emulator's modem sometimes drops the first fake SMS right after boot: send it
    # again once if nothing arrived (the phone app itself is not involved in that).
    adb("emu", "sms", "send", "4512345678", "Hej fra mor", check=False)
    try:
        sms: SmsReceived = desktop.wait_for(SmsReceived, timeout=40,
                                            match=lambda event: "Hej fra mor" in event.body)
    except AssertionError:
        adb("emu", "sms", "send", "4512345678", "Hej fra mor", check=False)
        sms = desktop.wait_for(SmsReceived, timeout=60,
                               match=lambda event: "Hej fra mor" in event.body)
    ok("new SMS is pushed to the PC right away")
    threads = desktop.run(desktop.client.sms_threads(phone))
    assert any(str(t.get("thread_id")) == sms.thread_id for t in threads), threads
    messages = desktop.run(desktop.client.sms_messages(phone, sms.thread_id))
    assert any("Hej fra mor" in m.get("body", "") for m in messages), messages
    ok("PC reads SMS threads and messages")
    desktop.run(desktop.client.send_sms(phone, "4512345678", "Svar fra PC'en"))
    deadline = time.time() + 30
    while time.time() < deadline:
        messages = desktop.run(desktop.client.sms_messages(phone, sms.thread_id))
        if any(m.get("outgoing") and "Svar fra PC" in m.get("body", "") for m in messages):
            break
        time.sleep(2)
    else:
        raise AssertionError(f"sent SMS not in the thread: {messages}")
    ok("PC sends an SMS through the phone")

    # ---- Find my phone + remote control ---------------------------------------
    assert desktop.run(desktop.client.find_phone(phone, True)) is True
    time.sleep(2)
    shot("22-find-phone")
    assert screen_has("Find telefon", 5) or "Find telefon" in shell(
        "dumpsys notification --noredact", check=False), "no find-phone notification"
    assert desktop.run(desktop.client.find_phone(phone, False)) is False
    ok("find my phone rings and stops from the PC")
    assert desktop.run(desktop.client.set_volume(phone, 40)) in range(30, 51)
    desktop.run(desktop.client.speak(phone, "Hej fra PC'en"))
    ok("remote volume and read-aloud")

    # ---- Screenshot on demand: the user allows it, the PNG lands on the PC -----
    desktop.events.clear()
    desktop.run(desktop.client.request_screenshot(phone))
    time.sleep(3)
    shot("23-screenshot-consent")
    # The app asks for the whole screen, so Android shows a single confirm button.
    tap_text("(?i)^(start now|start|share screen|start nu|del skærm)$", timeout=20)
    picture: FileReceived = desktop.wait_for(
        FileReceived, timeout=60, match=lambda e: e.path.name.startswith("Skaermbillede-"))
    assert picture.path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "screenshot is not a PNG"
    ok("screenshot on demand arrives on the PC as a PNG")
    desktop.run(desktop.client.set_wallpaper(phone, picture.path))
    ok("wallpaper set from the PC")


def bluetooth_checks(desktop: Desktop, phone: Peer) -> None:
    """The real app's Bluetooth bridge against the PC's bridge (bluetooth.py).

    The emulator has no usable Bluetooth, so the app also serves the bridge on a test
    port (files/bt_debug_port). Everything above RFCOMM is the real code on both sides.
    """
    import socket

    from h4xtor_share import bluetooth

    shell(f"pm grant {PKG} android.permission.BLUETOOTH_CONNECT", check=False)
    shell(f"run-as {PKG} sh -c 'echo 47495 > files/bt_debug_port'")
    adb("forward", "tcp:47496", "tcp:47495")
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(2)
    tap_text("^Del$")
    time.sleep(1)
    # The card is the last one on the page, right above the bottom navigation: check that
    # the switch really turned on, and nudge the page up before trying again.
    for _ in range(3):
        tap_text("^Del$")  # a stray tap may have opened another tab
        time.sleep(1)
        assert scroll_to("^Tillad forbindelse via Bluetooth$"), "Bluetooth card missing"
        tap_text("^Tillad forbindelse via Bluetooth$")
        time.sleep(2)
        if screen_has("(?i)^(allow|tillad)$", 3):  # permission dialog if pm grant was not enough
            tap_text("(?i)^(allow|tillad)$")
            time.sleep(1)
        if 'flag_bluetooth" value="true"' in prefs():
            break
        shell("input swipe 540 1500 540 1000 400")
        time.sleep(1)
    shot("26b-bluetooth-on")
    assert 'flag_bluetooth" value="true"' in prefs(), "could not switch Bluetooth on in the app"
    bridge = None
    for _ in range(10):
        try:
            link = socket.create_connection(("127.0.0.1", 47496), timeout=5)
            link.settimeout(None)
            candidate = bluetooth.Bridge(link, desktop.config.device_id, desktop.port).start()
            if candidate.wait_hello(5) == phone.device_id:
                bridge = candidate
                break
        except (OSError, ConnectionError):
            pass
        time.sleep(1.5)
    assert bridge is not None, "the phone's Bluetooth bridge never answered"
    ok("Bluetooth bridge: PC and phone say hello")

    # PC -> phone through the bridge
    over_bt = Peer(phone.device_id, phone.name, "127.0.0.1", bridge.port, phone.fingerprint,
                   "android", "bluetooth", phone.capabilities)
    desktop.run(desktop.client.send_clipboard(over_bt, "Hej via Bluetooth"))
    time.sleep(2)
    assert "Hej via Bluetooth" in prefs(), "text over Bluetooth did not reach the phone"
    ok("Bluetooth: text PC -> phone")
    desktop.run(desktop.client.send_link(over_bt, "https://example.com/via-bluetooth"))
    time.sleep(3)
    assert "via-bluetooth" in prefs(), "link over Bluetooth did not reach the phone"
    ok("Bluetooth: link PC -> phone")
    movie = WORK / "bt-film.bin"
    movie.write_bytes(os.urandom(2 * 1024 * 1024 + 123))  # not a whole number of pieces
    ids: set[str] = set()
    desktop.run(desktop.client.send_file(over_bt, movie, lambda p: ids.add(p.transfer_id)),
                timeout=180)
    time.sleep(2)
    listing = shell("ls -l /sdcard/Download/h4xtor-share/", check=False)
    assert "bt-film.bin" in listing and str(movie.stat().st_size) in listing, listing
    ok("Bluetooth: 2 MB file PC -> phone (in pieces), complete")
    # The PC lost the phone's last answer and tries again with the same id: no second copy.
    desktop.client._resumable[(phone.device_id, str(movie.resolve()))] = ids.pop()
    desktop.run(desktop.client.send_file(over_bt, movie, lambda _p: None), timeout=60)
    time.sleep(2)
    listing = shell("ls /sdcard/Download/h4xtor-share/", check=False)
    assert listing.count("bt-film") == 1, listing
    ok("Bluetooth: a retry after a lost answer does not save the file twice on the phone")
    album = WORK / "BTMappe"
    (album / "sub").mkdir(parents=True)
    (album / "sub" / "c.bin").write_bytes(os.urandom(300_000))
    (album / "d.txt").write_text("d")
    desktop.run(desktop.client.send_folder(over_bt, album, lambda _p: None), timeout=180)
    time.sleep(2)
    listing = shell("ls -lR /sdcard/Download/h4xtor-share/BTMappe", check=False)
    assert "c.bin" in listing and "300000" in listing and "d.txt" in listing, listing
    ok("Bluetooth: folder PC -> phone")

    # phone -> PC: the phone now routes this PC over the bridge
    # The files above may have moved the app to Overførsler: go back to the Del tab first.
    linked = False
    for _ in range(3):
        shell(f"am start -W -n {PKG}/.MainActivity")
        time.sleep(2)
        tap_text("^Del$")
        time.sleep(1)
        if scroll_to("^Forbundet via Bluetooth$"):
            linked = True
            break
    assert linked, "phone does not show the Bluetooth link"
    shot("27-bluetooth-linked")
    before = bridge.opened
    desktop.events.clear()
    for attempt in range(2):
        tap_text("^Del$")
        time.sleep(1)
        box = next(n for n in ui_nodes() if n.get("class") == "android.widget.EditText")
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", box.get("bounds")))
        shell(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")
        shell("input keyevent KEYCODE_MOVE_END " + " ".join(["KEYCODE_DEL"] * 40))
        shell(f"input text viabluetooth{attempt}")
        time.sleep(1.5)
        tap_text("^Send$")
        try:
            desktop.wait_for(ClipboardReceived, timeout=25,
                             match=lambda e: e.text.startswith("viabluetooth"))
            break
        except AssertionError:
            if attempt:
                raise
    assert bridge.opened > before, "phone -> PC did not use the Bluetooth bridge"
    ok("Bluetooth: text phone -> PC through the bridge")

    # File phone -> PC over the bridge (sent in small pieces), then reopening must not resend.
    shell("input keyevent KEYCODE_BACK", check=False)  # hide the keyboard
    out = shell("content query --uri content://media/external/downloads --projection _id "
                "--where \"_display_name='ferie.jpg'\"", check=False)
    found = re.search(r"_id=(\d+)", out)
    assert found, out
    uri = f"content://media/external/downloads/{found.group(1)}"
    share = (f"am start -W -a android.intent.action.SEND -t image/jpeg "
             f"--eu android.intent.extra.STREAM {uri} -n {PKG}/.ShareTargetActivity")
    desktop.events.clear()
    shell(share)
    tap_text("^AdminPC$", timeout=20)  # two PCs are paired: the sheet asks
    time.sleep(2)
    shot("27b-bluetooth-file-progress")
    assert bridge.busy, "the file did not go over the Bluetooth bridge"
    received: FileReceived = desktop.wait_for(FileReceived, timeout=120)
    assert received.path.read_bytes() == (WORK / "ferie.jpg").read_bytes(), "file changed"
    deadline = time.time() + 20  # the sheet shows "✓ Sendt" and closes by itself
    while "ShareTargetActivity" in shell("dumpsys activity activities | grep -i resumed",
                                         check=False) and time.time() < deadline:
        time.sleep(1)
    shot("27c-bluetooth-file-sent")
    assert time.time() < deadline, "the share sheet hangs after the file arrived"
    ok("Bluetooth: 3 MB file phone -> PC through the bridge, the sheet finishes by itself")
    time.sleep(3)
    desktop.events.clear()
    shell(f"am start -W -f 0x00100000 {share[len('am start -W '):]}")  # reopened from history
    time.sleep(3)
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(12)
    again = [e for e in desktop.events if isinstance(e, FileReceived)]
    assert not again, f"the file was sent again when the app was reopened: {again}"
    assert len(list((WORK / "AdminPC-in").glob("ferie*"))) == 2, "unexpected copies on the PC"
    ok("Bluetooth: reopening the app does not send the file again")
    # Link lost: the phone goes back to its Wi-Fi route by itself.
    bridge.close()
    time.sleep(4)
    # Not BACK to hide the keyboard: with the keyboard already gone it closes the app.
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(1)
    tap_text("^Del$")
    time.sleep(1)
    # The card sits below the fold: scroll to it, then its title is plain "Bluetooth" again.
    assert scroll_to("^Bluetooth$"), "phone still shows the Bluetooth link"
    assert not screen_has("^Forbundet via Bluetooth$", 2), "phone still shows the Bluetooth link"
    shot("28-bluetooth-ended")
    ok("Bluetooth: link lost, the phone switches back to Wi-Fi")

    # ---- A PC that was never on the phone's Wi-Fi: found and paired over Bluetooth ----
    stranger = Desktop("BTPC", 47482)
    pending = None
    for _ in range(10):
        try:
            link = socket.create_connection(("127.0.0.1", 47496), timeout=5)
            link.settimeout(None)
            candidate = bluetooth.Bridge(link, stranger.config.device_id, stranger.port).start()
            if candidate.wait_hello(5) == phone.device_id:
                pending = candidate
                break
        except (OSError, ConnectionError):
            pass
        time.sleep(1.5)
    assert pending is not None, "the phone did not answer a PC it is not paired with"
    time.sleep(2)
    assert not pending.closed, "the phone dropped the Bluetooth link of a new PC"
    info = stranger.run(stranger.client.get_info("127.0.0.1", pending.port))
    assert info.device_id == phone.device_id
    over = Peer(info.device_id, info.name, "127.0.0.1", pending.port, info.fingerprint,
                "android", "bluetooth", info.capabilities)
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(2)
    response = stranger.run(stranger.client.request_pairing(over))
    code = ""
    deadline = time.time() + 20
    while not code and time.time() < deadline:
        for node in ui_nodes():
            if re.fullmatch(r"\d{3} \d{3}", node.get("text") or ""):
                code = (node.get("text") or "").replace(" ", "")
        time.sleep(0.5)
    assert code, "the phone did not show a pairing code for the Bluetooth PC"
    shot("29-bluetooth-pair-code")
    tap_text("^OK$")
    stranger.run(stranger.client.confirm_pairing(over, str(response["pairing_id"]), code))
    assert stranger.config.is_trusted(phone.device_id), "the PC did not store the pairing"
    stored = ""
    for _ in range(20):  # SharedPreferences.apply() writes to disk a moment later
        stored = prefs()
        if f"out_token_{stranger.config.device_id}" in stored and "known_peers" in stored \
                and stranger.config.device_id in stored.split("known_peers", 1)[1]:
            break
        time.sleep(0.5)
    assert f"out_token_{stranger.config.device_id}" in stored, (
        "the phone did not trust the PC; tokens: "
        + ", ".join(re.findall(r'name="(out_token_[0-9a-f]+)"', stored)))
    known = re.search(r'name="known_peers">(.*?)</string>', stored, re.S)
    assert known and stranger.config.device_id in known.group(1), "PC not remembered"
    assert "127.0.0.1" not in known.group(1), "the bridge address was saved as the PC's address"
    ok("Bluetooth: a new PC finds the phone and pairs with a code over Bluetooth")
    stranger.run(stranger.client.send_clipboard(over, "Parret via Bluetooth"))
    time.sleep(2)
    assert "Parret via Bluetooth" in prefs(), "text over the new Bluetooth pairing did not arrive"
    # Android shows its own clipboard pop-up for the new text: get it out of the way first,
    # or the taps below land on it instead of the app.
    linked = False
    for _ in range(3):
        shell("input keyevent KEYCODE_BACK", check=False)
        shell("input keyevent KEYCODE_HOME", check=False)
        shell("cmd statusbar collapse", check=False)
        time.sleep(5)
        shell(f"am start -W -n {PKG}/.MainActivity")
        time.sleep(2)
        try:
            tap_text("^Del$", timeout=8)
        except AssertionError:
            continue
        time.sleep(1)
        if scroll_to("^Forbundet via Bluetooth$"):
            linked = True
            break
    assert linked, "phone does not use the link for the new PC"
    shot("29b-bluetooth-paired-new-pc")
    ok("Bluetooth: the phone keeps using the link for the PC it just paired with")
    stranger.run(stranger.client.unpair(over))  # leave only the main PCs for the next checks
    time.sleep(2)
    pending.close()


def update_checks() -> None:
    """Older version installed → finds the new one on a fake GitHub → updates → reopens."""
    import hashlib
    import http.server
    import json

    from h4xtor_share import __version__ as new_version  # == the APK's versionName (tested)

    apk = APK.read_bytes()
    prefix = "/h4xtor/h4xtor-share/releases/download/v" + new_version + "/"
    files = {
        prefix + "h4xtor-share-android.apk": apk,
        prefix + "h4xtor-share-android.apk.sha256":
            f"{hashlib.sha256(apk).hexdigest()}  h4xtor-share-android.apk\n".encode(),
        prefix + "CHANGELOG.md": (ROOT / "CHANGELOG.md").read_bytes(),
    }
    port = 8765
    base = f"http://127.0.0.1:{port}"
    files["/repos/h4xtor/h4xtor-share/releases/latest"] = json.dumps({
        "tag_name": f"v{new_version}",
        "assets": [{"name": path.rsplit("/", 1)[1], "browser_download_url": base + path}
                   for path in files if path.startswith(prefix)],
    }).encode()

    class Fake(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = files.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *_args) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    adb("reverse", f"tcp:{port}", f"tcp:{port}")

    adb("install", "-r", "-d", str(OLD_APK), timeout=240)  # same key, lower version
    old = shell(f"dumpsys package {PKG} | grep versionName").strip()
    assert new_version not in old, old
    shell(f"run-as {PKG} sh -c 'mkdir -p files && echo {base} > files/update_source'")
    shell(f"appops set {PKG} REQUEST_INSTALL_PACKAGES allow", check=False)
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(4)
    if not screen_has(rf"Version {re.escape(new_version)} er klar", 4):
        tap_text("^Indstillinger$")
        assert scroll_to("Søg efter opdatering nu"), "no update button in Indstillinger"
        tap_text("Søg efter opdatering nu")
    assert screen_has(rf"Version {re.escape(new_version)} er klar", 30), "update not offered"
    assert screen_has("Nyt", 5), "changelog missing in the update dialog"
    shot("60-update-offered")
    ok(f"{old} finds {new_version} and shows what is new")
    tap_text("^Opdatér nu$")
    assert screen_has("^(Update|Opdater|Opdatér|Install|Installer)$", 60), "no Android confirmation"
    shot("61-android-asks")
    tap_text("^(Update|Opdater|Opdatér|Install|Installer)$")
    deadline = time.time() + 120
    while new_version not in shell(f"dumpsys package {PKG} | grep versionName", check=False):
        assert time.time() < deadline, "the new version was not installed"
        time.sleep(2)
    ok(f"checksum verified and updated to {new_version} after Android's confirmation")
    deadline = time.time() + 30
    reopened = noted = False
    while time.time() < deadline and not (reopened or noted):
        resumed = "dumpsys activity activities | grep -E 'mResumedActivity|topResumed'"
        reopened = PKG in shell(resumed, check=False)
        noted = "Opdateret" in shell("dumpsys notification --noredact", check=False)
        time.sleep(2)
    assert reopened or noted, "neither reopened nor 'Opdateret – tryk for at åbne'"
    shot("62-after-update")
    if not reopened:
        shell("cmd statusbar expand-notifications", check=False)
        tap_text("Opdateret – tryk for at åbne", 15)  # what the user would tap
    assert screen_has(rf"Velkommen til version {re.escape(new_version)}", 30), "no welcome"
    shot("63-welcome")
    ok("reopened after the update" if reopened else "'Opdateret – tryk for at åbne' reopens it")
    tap_text("^Fint$")
    assert shell(f"pidof {PKG}", check=False).strip(), "app not running after the update"
    shell(f"run-as {PKG} rm files/update_source", check=False)
    server.shutdown()


def netshare_checks(desktop: Desktop, phone: Peer) -> None:
    """Wi-Fi + 5G: the PC tunnels real web traffic out over the emulator's mobile data."""
    assert phone.supports("net-gateway"), "phone does not advertise net-gateway"
    status = desktop.run(desktop.client.net_share_status(phone))
    assert status["enabled"] is False, status
    merge = NetMerge(47490, adapters=lambda: [])
    desktop.run(merge.start())
    merge.set_phone(phone.device_id, phone.name, desktop.client.net_route(phone))
    link = merge.links[f"phone:{phone.device_id}"]
    desktop.run(merge.probe(link))
    assert not link.healthy, "phone tunnelled while sharing was off"
    ok("mobile data sharing is off by default and the phone refuses tunnels")

    open_settings_row("^Del mobildata med PC'en$")
    assert "flag_net_share\" value=\"true" in prefs(), "share toggle not saved"
    deadline = time.time() + 60
    while not desktop.run(desktop.client.net_share_status(phone))["enabled"]:
        assert time.time() < deadline, "mobile data never became ready on the phone"
        time.sleep(2)
    desktop.run(merge.probe(link))
    assert link.healthy, "probe through the phone's mobile data failed"
    ok("phone shares its mobile data; the PC's probe through it succeeds")

    async def fetch(url: str) -> str:
        import aiohttp

        proxy = f"http://127.0.0.1:{merge.port}"
        async with aiohttp.ClientSession(trust_env=False) as session, session.get(
            url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            assert response.status == 200, (url, response.status)
            return await response.text()

    before = link.received
    assert "Example Domain" in desktop.run(fetch("https://example.com/"))
    assert "Example Domain" in desktop.run(fetch("http://example.com/"))
    assert link.received > before and link.connections >= 2, link
    ok("HTTPS (CONNECT) and HTTP web pages load through the phone's 5G")
    shell(f"am start -W -n {PKG}/.MainActivity")  # re-render: the card shows the counter
    time.sleep(2)
    tap_text("^Indstillinger$")
    time.sleep(1)
    assert scroll_to("^Del mobildata med PC'en$")
    shell("input swipe 540 1300 540 1000 400")  # the status line sits under the title
    time.sleep(1)
    assert screen_has("Deler nu", 5), "phone does not show that it is sharing"
    shot("24-mobile-data-shared")
    tap_text("^Del mobildata med PC'en$")  # switch it off again
    time.sleep(2)
    assert desktop.run(desktop.client.net_share_status(phone))["enabled"] is False
    desktop.run(merge.stop())
    ok("switching sharing off on the phone stops it")


def media_uri(name: str) -> str:
    for _ in range(15):
        out = shell("content query --uri content://media/external/downloads --projection _id "
                    f"--where \"_display_name='{name}'\"", check=False)
        match = re.search(r"_id=(\d+)", out)
        if match:
            return f"content://media/external/downloads/{match.group(1)}"
        time.sleep(1)
    raise AssertionError(f"{name} is not in MediaStore")


def queue_checks(desktop: Desktop, phone: Peer) -> None:
    """Five files shared at once: three send, two wait "I kø"; Pause alle / Fortsæt alle work."""
    names = [f"koe{index}.bin" for index in range(1, 6)]
    sources = {}
    for name in names:
        source = WORK / name
        source.write_bytes(os.urandom(4 * 1024 * 1024))
        sources[name] = source
        desktop.run(desktop.client.send_file(phone, source, lambda _p: None), timeout=120)
    uris = [media_uri(name) for name in names]
    desktop.events.clear()
    desktop.server.receive_delay = 8.0  # ~30 s per file: long enough to see the queue and pause it
    # Share one file at a time like a user: each sheet starts sending, then "Fortsæt i
    # baggrunden" closes it (a second `am start` would only bring the open sheet back).
    for uri in uris:
        shell("am start -W -a android.intent.action.SEND -t application/octet-stream "
              f"--eu android.intent.extra.STREAM {uri} -n {PKG}/.ShareTargetActivity")
        tap_text("Fortsæt i baggrunden")
        time.sleep(0.5)
    shell(f"am start -W -n {PKG}/.MainActivity")
    tap_text("^Overførsler$")
    assert screen_has(r"^I kø · nr\. 1$", 20), "queued files are not shown as waiting"
    assert screen_has("^Sender$", 5), "running files are not shown as sending"
    shot("30-queue")
    ok("five files at once: three send, the rest wait as 'I kø' (no row stuck at 0 %)")

    tap_text("^Pause alle$")
    if not screen_has("^På pause$", 8) and screen_has("^Pause alle$", 2):
        tap_text("^Pause alle$")  # a slow emulator can drop a tap; once more
    assert screen_has("^På pause$", 15), "Pause alle did not pause"
    assert not screen_has("^Sender$", 3), "a file kept sending after Pause alle"
    shot("31-paused")
    ok("Pause alle pauses every send")

    desktop.server.receive_delay = 0.0
    tap_text("^Fortsæt alle$")
    if screen_has("^Fortsæt alle$", 5) and not screen_has("^(Sender|I kø)", 1):
        tap_text("^Fortsæt alle$")
    received = [desktop.wait_for(FileReceived, timeout=120) for _ in names]
    by_name = {event.path.name: event.path for event in received}
    for name, source in sources.items():
        stem = name.removesuffix(".bin")
        got = next((path for key, path in by_name.items() if key.startswith(stem)), None)
        assert got is not None, f"{name} never arrived ({sorted(by_name)})"
        assert got.read_bytes() == source.read_bytes(), f"{name} changed after pause and resume"
    assert not screen_has(r"^(I kø|Sender|På pause)", 5), "a row is still open after all arrived"
    shot("32-resumed-done")
    ok("Fortsæt alle continues where each file stopped; all five byte-identical on the PC")
    tap_text("^Del$")  # the next steps start from the Del tab (the app reopens on the last tab)


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
    mascot_checks()

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
    shell("setprop log.tag.h4xtor DEBUG", check=False)  # log every click the watcher sees
    time.sleep(3)
    bound = shell("dumpsys accessibility", check=False)
    assert "CopyWatchService" in bound, "copy watcher not bound"
    def copy_in_contacts(word: str) -> bool:
        """Copy *word* in the Contacts app; True once the PC has it."""
        shell("am start -W -a android.intent.action.INSERT -t vnd.android.cursor.dir/contact "
              f"-e name {word}")
        time.sleep(4)
        def field_box() -> tuple[int, int, int, int]:
            for _ in range(10):
                node = next((n for n in ui_nodes() if (n.get("text") or "") == word), None)
                if node is not None:
                    return tuple(map(int, re.findall(r"\d+", node.get("bounds"))))
                time.sleep(1)
            raise AssertionError("contact editor with the test text is not on screen")

        shot("14-copy-other-app")
        x1, y1, x2, y2 = field_box()
        desktop.events.clear()
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        shell(f"input swipe {cx} {cy} {cx} {cy} 900")  # long-press
        time.sleep(3)  # the keyboard may slide in and move the form
        shot("15-long-press")
        # The text toolbar is a popup that `uiautomator dump` cannot see, so tap it by position
        # (pixel_7 profile): it floats 40 px above the field. Re-measure: the form can move.
        x1, y1, _, _ = field_box()
        shell(f"input tap {x1 + 248} {y1 - 40}")  # "Select all"
        time.sleep(3)
        shot("16-selected")
        x1, y1, _, _ = field_box()
        # `uiautomator dump` suppresses accessibility services while it runs; give the
        # system a moment to bind the copy watcher again before tapping Copy.
        time.sleep(3)
        shell(f"input tap {x1 + 381} {y1 - 40}")  # "Copy" (Translate | Cut | Copy | Paste | ⋮)
        time.sleep(1.5)
        shot("17-copied")
        (SHOTS / "accessibility.txt").write_text(shell("dumpsys accessibility", check=False),
                                                  encoding="utf-8")
        try:
            # 45 s: a copy made while the PC briefly looked offline is resent when it is back.
            desktop.wait_for(ClipboardReceived, timeout=45, match=lambda e: e.text == word)
        except AssertionError:
            return False
        return True

    # The emulator's Contacts app sometimes hangs ("isn't responding") and swallows the
    # position-based taps; then try once more with a fresh word.
    if not copy_in_contacts("telefonkopi"):
        print("WARN copy in Contacts not delivered, retrying once")
        shell("input keyevent BACK", check=False)
        shell("input keyevent BACK", check=False)
        assert copy_in_contacts("telefonkopito"), "copy in another app never reached the PC"
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
    queue_checks(desktop, phone)

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

    # ---- Work PC chosen, then home: the PC that is online gets it -------------
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(3)
    assert scroll_to("^AdminPC$"), "AdminPC missing from the device list"
    tap_text("^AdminPC$")  # remembered choice (the work PC)
    time.sleep(1)
    desktop.run(desktop.server.stop())  # left work: AdminPC is gone
    # Next morning at home: a fresh screen (the service and its transfer list keep running).
    shell(f"am start -W -f 0x10008000 -n {PKG}/.MainActivity")  # NEW_TASK | CLEAR_TASK
    time.sleep(12)  # health pings: AdminPC offline, Bærbar online
    shot("18-home-other-pc")
    laptop.events.clear()

    def send_from_home(text: str) -> bool:
        # A slow emulator can drop the tap or the typing: check the field before Send.
        for _ in range(3):
            box = next(n for n in ui_nodes() if n.get("class") == "android.widget.EditText")
            if (box.get("text") or "") == text:
                break
            x1, y1, x2, y2 = map(int, re.findall(r"\d+", box.get("bounds")))
            shell(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")
            shell("input keyevent KEYCODE_MOVE_END " + " ".join(["KEYCODE_DEL"] * 40))
            shell(f"input text {text}")
            time.sleep(1.5)
        tap_text("^Send$")
        try:
            laptop.wait_for(ClipboardReceived, timeout=20, match=lambda e: e.text == text)
        except AssertionError:
            return False
        return True

    if not send_from_home("hjemme-hp"):
        print("WARN text from home not delivered, retrying once")
        shot("18b-home-retry")
        assert send_from_home("hjemme-hp2"), "the PC that is online never got the text"
    ok("remembered PC offline: phone sends to the PC that is online")
    shell("input keyevent BACK", check=False)  # hide the keyboard
    desktop.run(desktop.server.start())  # back at work
    time.sleep(10)

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
    # The folder send just switched the app to Overførsler; a tap during that
    # re-render can be lost, so tap the tab again until the button shows up.
    for _ in range(3):
        tap_text("^Indstillinger$")
        time.sleep(1)
        if scroll_to("^Test hastighed til PC$"):
            break
    else:
        raise AssertionError("speed test button missing")
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

    # ---- Wi-Fi Direct: the user picks the network name and code ---------------
    # Needs no Wi-Fi Direct hardware: the choice is stored and used at the next start.
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(2)
    tap_text("^Del$")
    time.sleep(1)
    # The live device list can re-render between the UI dump and the tap, so the tap
    # sometimes lands on nothing: open the dialog again until its fixed label is up.
    for _ in range(3):
        assert scroll_to("^Vælg navn og kode$"), "Wi-Fi Direct 'Vælg navn og kode' missing"
        tap_text("^Vælg navn og kode$")
        if screen_has("^DIRECT-h4-$", 5):
            break
    else:
        raise AssertionError("Wi-Fi Direct name dialog did not open")

    def fill(index: int, value: str) -> None:
        # The dialog's fields: the EditTexts at or below its fixed "DIRECT-h4-" label.
        nodes = ui_nodes()
        label = next(n for n in nodes if (n.get("text") or "") == "DIRECT-h4-")
        top = int(re.findall(r"\d+", label.get("bounds"))[1])
        boxes = [
            n for n in nodes
            if n.get("class") == "android.widget.EditText"
            and int(re.findall(r"\d+", n.get("bounds"))[3]) > top
        ]
        boxes.sort(key=lambda n: int(re.findall(r"\d+", n.get("bounds"))[1]))
        box = boxes[index]
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", box.get("bounds")))
        shell(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")
        shell("input keyevent KEYCODE_MOVE_END " + " ".join(["KEYCODE_DEL"] * 70))
        shell(f"input text {value}")
        time.sleep(0.8)

    fill(0, "Lennart")
    fill(1, "kort")
    tap_text("^Gem$")
    assert screen_has("Koden skal være mindst 8 tegn", 5), "too short code was not refused"
    fill(1, "hemmelig123")
    assert not screen_has("Koden skal være mindst 8 tegn", 2), "old error stays while fixing"
    shot("26-wifi-direct-choose")
    tap_text("^Gem$")
    time.sleep(2)
    stored = prefs()
    assert '"str_p2p_ssid">DIRECT-h4-Lennart<' in stored, "chosen network name not stored"
    assert '"str_p2p_pass">hemmelig123<' in stored, "chosen code not stored"
    assert 'flag_p2p_custom" value="true"' in stored
    assert scroll_to("^Skift navn og kode$"), "button did not change to 'Skift navn og kode'"
    ok("Wi-Fi Direct: own network name and code are checked and stored")

    # ---- Wi-Fi Direct made by the PC: the phone shows "Forbind" at the top of Del ----------
    assert "wifi-direct-pc" in phone.capabilities, phone.capabilities
    assert scroll_to("^Scan PC'ens Wi-Fi-QR$"), "no way to join the PC's own network on the card"
    desktop.run(desktop.client.offer_pc_wifi_direct(
        phone, "DIRECT-h4-AdminPC", "hemmelig", ["192.168.137.1"]))
    shell(f"am start -W -n {PKG}/.MainActivity")
    tap_text("^Del$")
    time.sleep(2)
    assert scroll_to("^AdminPC har lavet Wi-Fi Direct$"), "offer card missing on the phone"
    assert screen_has("DIRECT-h4-AdminPC", 3)
    shot("26c-pc-wifi-offer")
    tap_text("^Ikke nu$")
    assert not screen_has("^AdminPC har lavet Wi-Fi Direct$", 3), "offer card did not go away"
    ok("Wi-Fi Direct made by the PC: the phone gets a 'Forbind' card (and can say 'Ikke nu')")

    bluetooth_checks(desktop, phone)

    v12_checks(desktop, phone)
    netshare_checks(desktop, phone)

    # ---- Bank-tilstand: one tap genuinely switches the accessibility service off ----------
    # Runs after v12_checks (which needs remote control on), while the copy watcher above has
    # left the accessibility service enabled so the card shows. Bank mode turns the sensitive
    # features off, so nothing after this relies on them.
    shell(f"am start -W -n {PKG}/.MainActivity")
    time.sleep(2)
    for _ in range(3):
        tap_text("^Indstillinger$")
        time.sleep(1)
        if scroll_to("^Bank-tilstand til$"):
            break
    else:
        raise AssertionError("Bank-tilstand card missing while the accessibility service is on")
    shot("30-bank-mode")
    tap_text("^Bank-tilstand til$")
    time.sleep(1)
    tap_text("^Slå fra$")  # confirm in the dialog
    time.sleep(4)
    enabled = shell("settings get secure enabled_accessibility_services", check=False).strip()
    assert "CopyWatchService" not in enabled, f"accessibility still on: {enabled}"
    assert 'flag_remote_control" value="false"' in prefs(), "remote control not switched off"
    shot("31-bank-mode-done")
    ok("Bank-tilstand til turns the accessibility service and remote control off")
    if screen_has("Næsten færdig", 5):  # SMS permission can't be revoked from code: finish prompt
        tap_text("^Senere$")

    # ---- Bank-tilstand fra restores the features it switched off --------------------------
    for _ in range(3):
        if scroll_to("^Bank-tilstand fra$"):
            break
        tap_text("^Indstillinger$")
        time.sleep(1)
    else:
        raise AssertionError("Bank-tilstand fra button missing while bank mode is on")
    tap_text("^Bank-tilstand fra$")
    time.sleep(3)
    assert 'flag_remote_control" value="true"' in prefs(), "remote control not restored"
    shot("32-bank-mode-off")
    ok("Bank-tilstand fra turns the features back on")
    if screen_has("send når du kopierer", 5):  # the accessibility re-enable prompt
        tap_text("^Senere$")

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

    update_checks()
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
            # The watcher's own lines and the system's view of activity starts (background
            # activity launch blocks, clipboard denials) live outside the app's pid.
            with open(SHOTS / "logcat-system.txt", "w", encoding="utf-8") as log:
                subprocess.run(["adb", "logcat", "-d", "-t", "5000", "-s", "h4xtor:V",
                                "ActivityTaskManager:V", "ClipboardService:V",
                                "BackgroundActivityStartController:V"],
                               stdout=log, timeout=30, check=False)
        except Exception:  # noqa: BLE001
            pass
