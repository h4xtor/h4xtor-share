"""End-to-end: real desktop app + its iPhone web page in a browser posing as an iPhone.

Run under a display (Xvfb):  python tests/e2e/iphone_web_e2e.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
WORK = Path(tempfile.mkdtemp(prefix="h4x-iphone-e2e-"))
os.environ["XDG_CONFIG_HOME"] = str(WORK / "desktop-config")
os.environ["XDG_DOWNLOAD_DIR"] = str(WORK / "downloads")

from playwright.sync_api import Page, sync_playwright  # noqa: E402

from h4xtor_share.app import H4xtorShareApp  # noqa: E402

SHOTS = Path(os.environ.get("E2E_SHOTS", WORK / "shots"))
SHOTS.mkdir(parents=True, exist_ok=True)


def pump(app: H4xtorShareApp, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def wait_until(app: H4xtorShareApp, what: str, check: Callable[[], bool], timeout=20.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if check():
            print("OK", what)
            return
        pump(app, 0.1)
    raise AssertionError(f"timed out: {what}")


def snap_pc(app: H4xtorShareApp, name: str) -> None:
    import subprocess

    pump(app, 0.6)
    subprocess.run(
        ["import", "-window", str(app.winfo_id()), str(SHOTS / f"pc-{name}.png")],
        timeout=20,
        check=False,
        capture_output=True,
    )


def clipboard(app: H4xtorShareApp) -> str:
    try:
        return app.clipboard_get()
    except Exception:  # noqa: BLE001 - empty clipboard
        return ""


def text_of(page: Page, selector: str) -> str:
    return page.locator(selector).inner_text()


def main() -> None:
    app = H4xtorShareApp(enable_tray=False)
    app.geometry("1300x900+0+0")
    app.config_store.open_links = False  # CI has no browser to open; links go to the clipboard
    pump(app, 2.0)
    incoming = app.config_store.incoming_directory

    app.show_page("iphone")
    app.set_web_enabled(True)
    pump(app, 1.5)
    url = app.web_share.url("127.0.0.1")
    snap_pc(app, "iphone-page")

    photo = WORK / "IMG_0042.jpg"
    photo.write_bytes(os.urandom(3 * 1024 * 1024))
    note = WORK / "Kvittering.pdf"
    note.write_bytes(b"%PDF-1.4 test")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)
        device = dict(playwright.devices["iPhone 15"])
        device.pop("default_browser_type", None)
        context = browser.new_context(**device, accept_downloads=True)
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = context.new_page()
        page.goto(url)
        wait_until(app, "page connects", lambda: page.locator("#main").is_visible())
        assert text_of(page, "#pc") == app.config_store.device_name
        page.screenshot(path=str(SHOTS / "iphone-home.png"))

        # iPhone → PC: photos and files.
        page.set_input_files("#files", [str(photo), str(note)])
        wait_until(
            app,
            "two uploads finished",
            lambda: page.locator("#uploads .bar.done").count() == 2,
            timeout=60,
        )
        wait_until(
            app,
            "files on the PC",
            lambda: (incoming / "IMG_0042.jpg").exists() and (incoming / "Kvittering.pdf").exists(),
        )
        assert (incoming / "IMG_0042.jpg").read_bytes() == photo.read_bytes()
        rows = [state for state in app.transfers.values() if state.peer_name == "iPhone"]
        assert len(rows) == 2 and all(state.status == "done" for state in rows), rows
        page.screenshot(path=str(SHOTS / "iphone-uploaded.png"))

        # iPhone → PC: text and a link land on the PC clipboard.
        page.fill("#text", "hej fra iphone")
        page.click("#send")
        wait_until(app, "text on PC clipboard", lambda: clipboard(app) == "hej fra iphone")
        page.fill("#text", "https://example.com/opskrift")
        page.click("#send")
        wait_until(
            app, "link on PC clipboard", lambda: clipboard(app) == "https://example.com/opskrift"
        )

        # PC → iPhone: a file and a text appear by themselves.
        sent = WORK / "Ferieplan.txt"
        sent.write_text("Skagen i juli", encoding="utf-8")
        app.send_to_iphone([sent])
        app.web_share.add_text("Wi-Fi kode: 4711")
        app._refresh_web_page()
        wait_until(app, "outbox on iPhone", lambda: page.locator("#outbox .item").count() == 2)
        page.screenshot(path=str(SHOTS / "iphone-from-pc.png"))
        with page.expect_download() as info:
            page.locator("#outbox a", has_text="Hent").first.click()
        downloaded = Path(info.value.path())
        assert downloaded.read_text(encoding="utf-8") == "Skagen i juli"
        wait_until(app, "PC sees it was fetched", lambda: app.web_share.outbox[-1].downloads == 1)
        page.locator("#outbox button", has_text="Kopiér").click()
        wait_until(app, "copied toast", lambda: "Kopieret" in text_of(page, "#toast"))

        # PC clipboard → iPhone.
        app.clipboard_clear()
        app.clipboard_append("tekst fra pc")
        page.click("#getclip")
        wait_until(app, "PC clipboard on iPhone", lambda: text_of(page, "#clip") == "tekst fra pc")
        snap_pc(app, "iphone-page-after")

        # A wrong key, a new link and switching off all lock the phone out.
        stranger = context.new_page()
        stranger.goto(url.split("?")[0] + "?k=gaet")
        wait_until(app, "wrong key is refused", lambda: stranger.locator("#lock").is_visible())
        stranger.screenshot(path=str(SHOTS / "iphone-locked.png"))
        app.new_web_link()
        page.reload()
        wait_until(app, "old link is refused", lambda: page.locator("#lock").is_visible())
        fresh = context.new_page()
        fresh.goto(app.web_share.url("127.0.0.1"))
        wait_until(app, "new link works", lambda: fresh.locator("#main").is_visible())
        app.set_web_enabled(False)
        wait_until(
            app, "switched off shows on iPhone", lambda: "svarer ikke" in text_of(fresh, "#pc")
        )
        browser.close()

    app.close()
    print("ALL OK – screenshots in", SHOTS)


if __name__ == "__main__":
    main()
