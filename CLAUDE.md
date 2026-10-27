# h4xtor share – notes for Claude Code

Local Android ⇄ PC sharing (files, folders, links, clipboard) with a Windows/macOS/Linux
desktop app, an Android app and a Chrome extension. Everything is local; nothing goes to a cloud.

## Talking to the owner (Lennart)

- Write to him in **Danish**: warm, short and in plain language. He does not code, so never paste code in chat.
- Start with what was done ("Her er resultatet!"), explain it briefly and end with **one** small next step.
- **Test everything before handing anything over.** He does not want near-finished apps.
  Design and every sharing function must work.
- When waiting on CI or builds, check back after **at most 10 minutes**, and always report the status.
  No text progress bars in chat. Progress lives in the live-status artifact
  https://claude.ai/artifact/B1o9t1UX1NCj4oM3pAzGe1: write its db doc `status/live`
  (`task`, `from`, `to` in %, `since`/`eta` ISO times it glides between, `updated`, `note`,
  `steps` = [{label, state: done|run|todo}]) at the start of a wait and at every check-in.
- GitHub (`h4xtor/h4xtor-share`, branch `main`) is the source of truth. You may commit, push and tag.

## Working folder

Lennart's local copy lives in `C:\Users\Lenna\Desktop\h4xtorshare` (a clone of `h4xtor/h4xtor-share`).
Never use the deleted repo `h4xtor/H4xtorShare` or old folders such as `C:\AI\FreeBUFFSHARE`.

## Layout

| Path | What it is |
|------|------------|
| `src/h4xtor_share/` | Desktop app (Python 3.11+, Tk, aiohttp). Entry: `app.py` (`H4xtorShareApp`) |
| `src/h4xtor_share/ui_kit.py` | Battle.net-style widgets: Theme, Button, Card, ScrollFrame, `HeroBanner` (Send page key art), `DeviceTiles`, `MonkeyActor` (hop/grin/point/nod), `render_backdrop` … |
| `src/h4xtor_share/server.py` / `client.py` | Protocol v1 (HTTPS on port 47474, pinned TLS fingerprints) |
| `src/h4xtor_share/local_api.py` | Loopback API on 127.0.0.1:47476, used by the Chrome extension |
| `src/h4xtor_share/web_share.py` + `web_page.py` | iPhone/browser sharing: plain HTTP on the LAN, port 47478, guarded by a random key in the QR link. Off until switched on (page "iPhone") |
| `src/h4xtor_share/bluetooth.py` | Bluetooth bridge ("h4xtor-bt/1"): multiplexes the normal HTTPS connections over one RFCOMM link. Android side: `BluetoothBridge.java` + `BluetoothController.java` (same frame bytes, tested on both sides). The PC connects; the phone listens |
| `src/h4xtor_share/wifidirect.py` / `wifidirect_host.py` | Wi-Fi Direct: the PC joins the phone's group / the PC makes its own network (Windows: WinRT `WiFiDirectAdvertisementPublisher` in legacy mode via a PowerShell helper; Linux: `nmcli` hotspot). Android side: `WifiDirectController.java` (phone hosts) and `WifiJoinController.java` (phone joins the PC's network with `WifiNetworkSpecifier`, then `POST /api/v1/wifi-direct/joined`) |
| `src/h4xtor_share/integration.py` | Windows integration: right-click menu (AllFilesystemObjects, NeverDefault), Send-to, autostart, Chrome |
| `src/h4xtor_share/updater.py` + `update_pages.py` | Auto-update from GitHub Releases (HTTPS, SHA-256), changelog parsing, the Windows swap helper (`--apply-update`) with rollback |
| `src/h4xtor_share/netmerge.py` + `netmerge_page.py` + `sysproxy.py` | "Wi-Fi + 5G" (net-merge style): local HTTP/SOCKS5 proxy on 127.0.0.1:47480 spreading connections over the PC's adapters and paired phones (pinned-TLS `CONNECT` to the phone's port 47474); system proxy via a PAC file so a crash never breaks the internet |
| `src/h4xtor_share/openers.py` | Opening and revealing files. Folders are **always** opened through `explorer.exe`, never through `os.startfile` |
| `src/h4xtor_share/chrome_extension/` | MV3 extension (popup + context menu) |
| `android/app/src/main/java/com/h4xtor/share/` | Android app (Java, minSdk 29). `MainActivity`, `ShareService`, `ShareTargetActivity`, `Ui` (design tokens), `LauncherBackdrop` + `HeroArt` (Battle.net backdrop and Del hero), `SpeedGraph`, `NetGateway` (shares mobile data) … |
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

The latest release is **v1.5.0**. Without tag-push rights, start a release from Actions → Release → Run workflow (tag input).


## Lennart's wish list (build in this order, one release each)

Every new feature gets an on/off switch on both sides (PC: Indstillinger → "Ekstra funktioner";
phone: the "Telefon på PC'en" card), a test, and the glass look (PC: `glass_image`; phone: `Ui.glass`).

1. Telefon-status på PC'en: battery, charging, signal; alerts when low/full — **v1.6.0**
2. Telefonens billeder på PC'en: gallery + one-click fetch, automatic photo backup on home Wi-Fi
3. Fælles udklipsholder-historik: last 50 copies from PC and phone, search, send again
4. Telefonen som fjernbetjening: touchpad, keyboard, media keys, PowerPoint clicker
5. Scan papir til PDF: PC asks, the phone's camera shoots, a straight PDF lands on the PC
6. Tænd/lås PC'en fra telefonen: Wake-on-LAN, lock, sleep, shut down
7. Del Wi-Fi med gæster: QR code with the Wi-Fi password on PC and phone
8. Telefonens skærm på PC'en: live mirror with mouse control
9. Svævende abe på skrivebordet: always-on-top drop target (drag a file → phone; click → clipboard)
10. Hvem ringer? på PC'en: caller name pops up, reject or quick SMS reply

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
- Wi-Fi Direct made by the PC depends on the Wi-Fi card/driver (Windows legacy Wi-Fi Direct) and
  NetworkManager on Linux; macOS cannot. CI proves the WinRT types load on Windows
  (`test_windows_winrt_types_load`) and that the phone shows the offer card; the radio part is
  only proven on real hardware. The phone joins with `WifiNetworkSpecifier` (Android shows a
  "Forbind" box, foreground only) and binds the app to that network while joined.
- Phone sends: three run at a time, the rest are `queued` ("I kø"). `pause` cancels the run and
  keeps the resumable id, so "Fortsæt" continues at the PC's offset. The e2e test slows the PC
  receiver with `ShareServer.receive_delay` to see the queue and pause it.
- The status dashboard (Claude artifact) only updates when Claude writes to it.
