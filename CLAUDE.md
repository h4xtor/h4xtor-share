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

## Layout

| Path | What it is |
|------|------------|
| `src/h4xtor_share/` | Desktop app (Python 3.11+, Tk, aiohttp). Entry: `app.py` (`H4xtorShareApp`) |
| `src/h4xtor_share/ui_kit.py` | Claude-style widgets: Theme, Button, Card, ScrollFrame, Monkey mascot … |
| `src/h4xtor_share/server.py` / `client.py` | Protocol v1 (HTTPS on port 47474, pinned TLS fingerprints) |
| `src/h4xtor_share/local_api.py` | Loopback API on 127.0.0.1:47476, used by the Chrome extension |
| `src/h4xtor_share/integration.py` | Windows integration: right-click menu (AllFilesystemObjects, NeverDefault), Send-to, autostart, Chrome |
| `src/h4xtor_share/openers.py` | Opening and revealing files. Folders are **always** opened through `explorer.exe`, never through `os.startfile` |
| `src/h4xtor_share/chrome_extension/` | MV3 extension (popup + context menu) |
| `android/app/src/main/java/com/h4xtor/share/` | Android app (Java, minSdk 29). `MainActivity`, `ShareService`, `ShareTargetActivity`, `SpeedGraph` … |
| `tests/` | pytest suite |
| `tests/e2e/chrome_extension_e2e.py` | Real desktop app + Chrome extension + simulated phone |
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

1. Bump the version in **four** places: `pyproject.toml`, `src/h4xtor_share/__init__.py`,
   `android/app/build.gradle` (versionCode + versionName) and `AppIdentity.VERSION`.
2. Push to `main` and wait until CI is green, including **android-e2e**.
3. `git tag vX.Y.Z && git push origin vX.Y.Z`. The Release workflow then attaches the .exe, APK and other builds.

The latest release is **v1.1.2**.

## Open issue (reported by Lennart, not yet fixed)

**Settings page in the .exe barely scrolls with the mouse wheel.** Root cause is in
`ui_kit.ScrollFrame`. It binds the wheel on `<Enter>` and unbinds it on `<Leave>` of the canvas
and of the inner frame. When the pointer moves onto any child widget, the inner frame receives
`<Leave>` and the wheel is unbound, so scrolling only works over empty gaps.

Fix:
- Bind the wheel once with `bind_all`.
- In the handler, scroll the ScrollFrame that contains the widget under the pointer
  (`winfo_containing(event.x_root, event.y_root)`, then walk up the parents).
- Use a sensible step: set `yscrollincrement` to about 40 px, or scroll in pixels.
- Add a test, then release v1.1.3.

## Known limits (be honest about these)

- Android only lets apps read the clipboard while they are in the foreground. Phone → PC clipboard
  sync therefore runs when the app is opened, from the notification, from the Quick Settings tile
  or via "Send til PC" in the text menu. PC → phone always works.
- The status dashboard (Claude artifact) only updates when Claude writes to it.
