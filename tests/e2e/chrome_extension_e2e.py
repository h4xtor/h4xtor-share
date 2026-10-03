"""End-to-end: real desktop app + real Chrome extension + a simulated phone.

Run under a display (Xvfb):  python tests/e2e/chrome_extension_e2e.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
WORK = Path(tempfile.mkdtemp(prefix="h4x-e2e-"))
os.environ["XDG_CONFIG_HOME"] = str(WORK / "desktop-config")
os.environ["XDG_DOWNLOAD_DIR"] = str(WORK / "downloads")

from playwright.sync_api import sync_playwright  # noqa: E402

from h4xtor_share.app import H4xtorShareApp  # noqa: E402
from h4xtor_share.client import PeerClient  # noqa: E402
from h4xtor_share.config import Config  # noqa: E402
from h4xtor_share.crypto import ensure_certificate, server_ssl_context  # noqa: E402
from h4xtor_share.models import ClipboardReceived, FileReceived, LinkReceived  # noqa: E402
from h4xtor_share.pairing import PairingInvite  # noqa: E402
from h4xtor_share.server import ShareServer  # noqa: E402

EXT = ROOT / "src" / "h4xtor_share" / "chrome_extension"
SHOTS = Path(os.environ.get("E2E_SHOTS", WORK / "shots"))
SHOTS.mkdir(parents=True, exist_ok=True)


class Phone:
    """A headless h4xtor-share node standing in for the Android phone."""

    def __init__(self) -> None:
        self.config = Config(WORK / "phone" / "config.json")
        self.config.data.update(
            device_name="Testtelefon",
            port=47490,
            platform="android",
            incoming_directory=str(WORK / "phone-in"),
        )
        self.config.save()
        cert, key, self.fp = ensure_certificate(self.config.path.parent, "Testtelefon")
        self.events: list[object] = []
        self.server = ShareServer(
            self.config,
            server_ssl_context(cert, key),
            self.fp,
            self.events.append,
            host="127.0.0.1",
        )
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(self.server.start(), self.loop).result(10)

    def invite(self) -> PairingInvite:
        return PairingInvite(
            self.config.device_id,
            "Testtelefon",
            self.fp,
            47490,
            ("127.0.0.1",),
            self.server.create_qr_secret(),
            "android",
        )

    def wait_for(self, kind: type, timeout: float = 20.0) -> object:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for event in self.events:
                if isinstance(event, kind):
                    self.events.remove(event)
                    return event
            time.sleep(0.1)
        raise AssertionError(f"phone never received {kind.__name__}")


def snap(app: H4xtorShareApp, name: str) -> None:
    """Screenshot the app window (for design review); never fails the test."""
    import subprocess

    pump(app, 0.6)
    try:
        app.lift()
        app.update()
        subprocess.run(["import", "-window", str(app.winfo_id()), str(SHOTS / f"pc-{name}.png")],
                       timeout=20, check=False, capture_output=True)
    except Exception as error:  # noqa: BLE001
        print("WARN screenshot", name, error)


def pump(app: H4xtorShareApp, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def main() -> None:
    phone = Phone()
    app = H4xtorShareApp(enable_tray=False)
    pump(app, 2.0)

    # Pair the desktop with the phone exactly like a QR scan would.
    peer = asyncio.run_coroutine_threadsafe(
        app.client.pair_with_qr(phone.invite()), app.runtime.loop
    ).result(15)
    app.event_queue.put(("pair_confirmed", peer))
    pump(app, 5.5)
    assert app.config_store.is_trusted(peer.device_id), "desktop did not trust phone"
    assert phone.config.is_trusted(app.config_store.device_id), "pairing was not mutual"
    status = app.peer_status.get(peer.device_id)
    assert status is not None and status.online, "phone not shown online"
    print("OK pairing + online status")
    app.geometry("1180x780")
    from h4xtor_share.models import Peer as _Peer

    stranger = _Peer("f" * 32, "Stues-PC", "192.168.1.77", 47474, "ab" * 32, "windows")
    app.peers[stranger.device_id] = stranger
    app._upsert_peer(stranger)
    snap(app, "01-share")

    # Serve an image for the "send image" flow.
    web_root = WORK / "web"
    web_root.mkdir()
    (web_root / "kat.png").write_bytes((EXT / "icons" / "icon128.png").read_bytes())
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 47499), partial(SimpleHTTPRequestHandler, directory=str(web_root))
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(WORK / "chrome-profile"),
            headless=False,
            executable_path=os.environ.get("CHROME_PATH") or None,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"],
        )
        worker = (
            context.service_workers[0]
            if context.service_workers
            else context.wait_for_event("serviceworker", timeout=15000)
        )
        ext_id = worker.url.split("/")[2]
        page = context.new_page()

        # Approve the extension in the desktop app automatically after the modal appears.
        def approve_soon() -> None:
            time.sleep(1.5)
            app.event_queue.put(("e2e_approve", None))

        popup = context.new_page()
        popup.set_viewport_size({"width": 340, "height": 520})
        popup.goto(f"chrome-extension://{ext_id}/popup.html")
        popup.wait_for_selector("#state-connect:not(.hidden)", timeout=10000)
        popup.screenshot(path=str(SHOTS / "ext-connect.png"))

        approvals: list[str] = []
        original = app._ask_extension_approval

        def auto(value: tuple) -> None:
            original(value)
            approvals.append(value[0])
            name, origin, loop, decision = value
            app.after(
                800,
                lambda: loop.call_soon_threadsafe(
                    lambda: decision.done() or decision.set_result(True)
                ),
            )

        app._ask_extension_approval = auto
        popup.click("#connect")
        deadline = time.time() + 20
        while time.time() < deadline and popup.locator("#state-ready.hidden").count():
            pump(app, 0.2)
        assert approvals, "approval modal never shown"
        popup.wait_for_selector("#state-ready:not(.hidden)", timeout=5000)
        assert "Testtelefon" in popup.inner_text("#devices")
        pump(app, 0.5)
        popup.screenshot(path=str(SHOTS / "ext-ready.png"))
        print("OK extension connected after approval")

        # Send text and a link from the popup composer.
        popup.fill("#text", "Hej fra Chrome")
        popup.click("#send-text")
        event = phone.wait_for(ClipboardReceived)
        assert event.text == "Hej fra Chrome"
        popup.fill("#text", "https://example.com/artikel")
        popup.press("#text", "Enter")
        event = phone.wait_for(LinkReceived)
        assert event.url == "https://example.com/artikel"
        print("OK text + link from popup")

        # Send the current tab.
        page.goto("http://127.0.0.1:47499/kat.png")
        page.bring_to_front()
        result = popup.evaluate(
            """async () => {
                const api = await import('./api.js');
                const list = await api.devices();
                await api.send(list[0].id, 'file-url', 'http://127.0.0.1:47499/kat.png');
                await api.send(list[0].id, 'link', 'http://127.0.0.1:47499/kat.png');
                return list.length;
            }"""
        )
        assert result == 1
        received = phone.wait_for(FileReceived, timeout=30)
        assert received.path.read_bytes() == (web_root / "kat.png").read_bytes()
        phone.wait_for(LinkReceived)
        print("OK image downloaded and sent as a real file")

        # A website must not be able to talk to the app.
        status_code = page.evaluate(
            """async () => {
                try { const r = await fetch('http://127.0.0.1:47476/v1/status');
                      return r.status; } catch (e) { return 'blocked'; }
            }"""
        )
        assert status_code in (403, "blocked"), status_code
        print("OK websites are blocked from the local API")
        context.close()

    # Phone -> desktop: link opens in the browser, clipboard text is applied.
    opened: list[str] = []
    app._open_link = lambda url: opened.append(url) or "chrome"
    client = PeerClient(phone.config, fingerprint=phone.fp)
    me = asyncio.run_coroutine_threadsafe(
        client.get_info("127.0.0.1", app.config_store.port), phone.loop
    ).result(10)
    asyncio.run_coroutine_threadsafe(client.send_link(me, "https://h4xtor.dk"), phone.loop).result(
        10
    )
    asyncio.run_coroutine_threadsafe(
        client.send_clipboard(me, "kopieret på telefonen"), phone.loop
    ).result(10)
    pump(app, 1.5)
    assert opened == ["https://h4xtor.dk"], opened
    assert app.clipboard_get() == "kopieret på telefonen"
    print("OK phone -> PC link opened + clipboard applied")

    # PC clipboard -> phone automatically.
    app.clipboard_clear()
    app.clipboard_append("kopieret på PC'en")
    pump(app, 2.5)
    event = phone.wait_for(ClipboardReceived)
    assert event.text == "kopieret på PC'en", event.text
    print("OK PC clipboard synced to phone automatically")

    # Right-click / Send to: a second launch hands files to the running app.
    from h4xtor_share import integration

    sample = WORK / "rapport.pdf"
    sample.write_bytes(b"%PDF-1.4 test" * 1000)
    app.select_peer(peer.device_id)
    for _ in range(2):  # Explorer starts one process per selected file
        assert integration.send_to_running_instance(
            app.config_store.path.parent,
            app.config_store.port + 1,
            {"cmd": "send", "paths": [str(sample)]},
        )
    pump(app, 3)
    received = phone.wait_for(FileReceived, timeout=30)
    assert received.path.read_bytes() == sample.read_bytes()
    print("OK right-click send of a file")
    for page in ("transfers", "history", "settings"):
        if page in app.pages:
            app.show_page(page)
            snap(app, f"02-{page}")
    app.show_page("share")
    app.update()
    app.close()

    # Same app in dark mode, for design review.
    dark = Config(app.config_store.path)
    dark.theme = "dark"
    dark.save()
    app = H4xtorShareApp(enable_tray=False)
    app.geometry("1180x780")
    pump(app, 4)
    snap(app, "03-share-dark")
    app.show_page("settings")
    snap(app, "04-settings-dark")
    app.close()
    print("ALL E2E CHECKS PASSED")


if __name__ == "__main__":
    main()
