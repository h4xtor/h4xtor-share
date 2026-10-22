# h4xtor share – notes for Claude Code

Local Android ⇄ PC sharing (files, folders, links, clipboard) with a Windows/macOS/Linux
desktop app, an Android app and a Chrome extension. Everything is local; nothing goes to a cloud.

## Talking to the owner (Lennart)

- Write to him in **Danish**: warm, short and in plain language. He does not code, so never paste code in chat.
- Start with what was done ("Her er resultatet!"), explain it briefly and end with **one** small next step.
- **Test everything before handing anything over.** He does not want near-finished apps.
  Design and every sharing function must work.
- When waiting on CI or builds, check back after **at most 10 minutes**, and always report the status.
- GitHub (`h4xtor/h4xtor-share`, branch `main`) is the source of truth. You may commit, push and tag.

## Working folder

Lennart's local copy lives in `C:\Users\Lenna\Desktop\h4xtorshare` (a clone of `h4xtor/h4xtor-share`).
Never use the deleted repo `h4xtor/H4xtorShare` or old folders such as `C:\AI\FreeBUFFSHARE`.

## Layout

| Path | What it is |
|------|------------|
| `src/h4xtor_share/` | Desktop app (Python 3.11+, Tk, aiohttp). Entry: `app.py` (`H4xtorShareApp`) |
| `src/h4xtor_share/ui_kit.py` | Claude-style widgets: Theme, Button, Card, ScrollFrame, Monkey mascot … |
| `src/h4xtor_share/server.py` / `client.py` | Protocol v1 (HTTPS on port 47474, pinned TLS fingerprints) |
| `src/h4xtor_share/local_api.py` | Loopback API on 127.0.0.1:47476, used by the Chrome extension |
| `src/h4xtor_share/web_share.py` + `web_page.py` | iPhone/browser sharing: plain HTTP on the LAN, port 47478, guarded by a random key in the QR link. Off until switched on (page "iPhone") |
| `src/h4xtor_share/bluetooth.py` | Bluetooth bridge ("h4xtor-bt/1"): multiplexes the normal HTTPS connections over one RFCOMM link. Android side: `BluetoothBridge.java` + `BluetoothController.java` (same frame bytes, tested on both sides). The PC connects; the phone listens |
| `src/h4xtor_share/integration.py` | Windows integration: right-click menu (AllFilesystemObjects, NeverDefault), Send-to, autostart, Chrome |
| `src/h4xtor_share/updater.py` + `update_pages.py` | Auto-update from GitHub Releases (HTTPS, SHA-256), changelog parsing, the Windows swap helper (`--apply-update`) with rollback |
| `src/h4xtor_share/openers.py` | Opening and revealing files. Folders are **always** opened through `explorer.exe`, never through `os.startfile` |
| `src/h4xtor_share/chrome_extension/` | MV3 extension (popup + context menu) |
| `android/app/src/main/java/com/h4xtor/share/` | Android app (Java, minSdk 29). `MainActivity`, `ShareService`, `ShareTargetActivity`, `SpeedGraph` … |
| `tests/` | pytest suite |
| `tests/e2e/chrome_extension_e2e.py` | Real desktop app + Chrome extension + simulated phone |
| `tests/e2e/iphone_web_e2e.py` | Real desktop app + its iPhone web page in Chromium posing as an iPhone |
| `tests/e2e/android_e2e.py` | Real APK in an emulator against the desktop core (CI only). Screenshots go to the `ci-shots` branch |
| `.github/workflows/ci.yml` | Tests (Win/macOS/Linux), both E2E suites, packaging, Android build. Pushing a `v*` tag makes a release |

## Commands

```bash
pip install -e ".[dev]"
ruff check .
pytest -q                                   # Tk tests need a display (Linux: xvfb-run -a)
python tests/e2e/chrome_extension_e2e.py    # needs playwright + chromium (set CHROME_PATH)
gradle -p android testDebugUnitTest lintDebug assembleDebug
```

## Releasing

1. Bump the version in **three** places: `pyproject.toml`, `src/h4xtor_share/__init__.py` and
   `android/app/build.gradle` (the default versionCode + versionName; `AppIdentity.VERSION` reads it).
2. Add a `## X.Y.Z – YYYY-MM-DD` entry with `### Nyt / Forbedret / Rettet` at the top of `CHANGELOG.md`.
   The apps parse it; tests and the release fail without it.
3. Push to `main` and wait until CI is green, including **android-e2e** (it updates an older APK to this one).
4. `git tag vX.Y.Z && git push origin vX.Y.Z`. The Release workflow attaches the .exe, APK, other builds,
   a `.sha256` per binary and `CHANGELOG.md` (fixed names: the in-app updater looks for them), and uses
   the changelog entry as release notes.

The latest release is **v1.3.8**. Without tag-push rights, start a release from Actions → Release → Run workflow (tag input).


## Known limits (be honest about these)

- Android only lets the focused app read the clipboard. Instant phone → PC sync uses the
  `CopyWatchService` accessibility service: a tap on "Kopiér"/"Copy" in any app briefly opens the
  invisible `ClipboardSendActivity`, which reads and sends. The user must switch it on once
  (Indstillinger → "Send med det samme, når du kopierer"); sideloaded APKs on Android 13+ first need
  App-info → ⋮ → "Tillad begrænsede indstillinger". Copies via keyboard shortcuts are not caught;
  then the app/notification/tile/"Send til PC" paths still work. PC → phone always works.
- Bluetooth needs the phone and PC paired in the OS Bluetooth settings first (and "Tillad forbindelse
  via Bluetooth" on in the phone app). Since v1.3.7 the PC finds phones with "Søg via Bluetooth"
  (paired devices whose class of device says phone; all when unknown) and can pair with the code
  over the link: the phone keeps an unpaired PC's link open for 10 minutes (`pending` in
  `BluetoothController`), and a peer reached only on Bluetooth is remembered with an empty address.
  It works on Windows and Linux only (no RFCOMM sockets in Python on macOS) and is 10–50× slower than Wi-Fi. CI tests the
  bridge over TCP (the emulator has no Bluetooth: `files/bt_debug_port`), so the radio part
  (Windows SDP lookup by UUID, Android `listenUsingRfcommWithServiceRecord`) is only proven on
  real hardware.
- The status dashboard (Claude artifact) only updates when Claude writes to it.
