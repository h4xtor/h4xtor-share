# Handoff – h4xtor share (2026-10-06)

Read `CLAUDE.md` first (talk to Lennart in Danish, short, no code in chat, test everything,
check CI at least every 10 minutes).

## Goal of this session
Give Lennart the **newest EXE (Windows) and APK (Android) that work and are fully tested**,
as files in the chat (SendUserFile, display "attach"), plus a short Danish summary.

## State when handed over
- Releases v1.1.0 … v1.1.6 exist. `main` has one commit after v1.1.6:
  `5194de4 Harden desktop code pairing (#11)` (not released yet).
- v1.1.4: instant phone→PC copy sync (`CopyWatchService` accessibility service, needs
  `canRetrieveWindowContent=true` + `flagRetrieveInteractiveWindows`, otherwise clicks in the
  floating text toolbar never arrive).
- v1.1.5: kept a copy made while the PC is offline (2 min), copy no longer restarts a stopped
  service, single-instance fix for multi-file right-click send (port claimed in `main()` before
  the window is built; `SO_REUSEADDR` off Windows, `SO_EXCLUSIVEADDRUSE` on Windows), shell
  paths refreshed on start, exe icon, `packaging/smoke_test.py` run in CI **and** release.
- v1.1.6 and #11 were done by other sessions – review what they changed (`git log v1.1.5..main`).

## Steps
1. Check CI on `main` is fully green (incl. **android-e2e**, **desktop-e2e** and the Windows
   smoke test). If #11 is green, release **v1.1.7** (bump the 4 version places, PR, merge,
   dispatch `release.yml` with `tag=v1.1.7` – this environment cannot push tags). If anything
   is red, fix it first; if a fix is not quick, deliver v1.1.6 instead and say so.
2. Download `h4xtor-share-windows.exe` and `h4xtor-share-android.apk` from the release.
   Verify: sha256 = release digest; APK versionName/versionCode, signed v2 with the same cert
   as earlier releases (sha256 prefix `bb19ab105575d9e0`), `res/xml/copy_watch.xml` flags 0x40;
   EXE FileVersion and bundled `h4xtor_share/chrome_extension/` (pyinstxtractor-ng, pefile,
   androguard work fine in a venv).
3. Run locally: `ruff check .`, `xvfb-run -a pytest -q` and `tests/e2e/chrome_extension_e2e.py`
   (Python 3.12 has tkinter here: `/usr/bin/python3.12 -m venv --system-site-packages`;
   Chrome: `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`). Look at the screenshots
   (`E2E_SHOTS=<dir>`, and the `ci-shots` branch for Android) – the monkey mascot must be on
   the "Velkommen til H4xtor Share" header on both PC and phone.
4. Send both files to Lennart with: what is new, that the monkey is there, and the one-time
   phone setup (Indstillinger → "Send med det samme, når du kopierer" → turn on "h4xtor share"
   under Hjælpefunktioner; if "Begrænset indstilling": App-info → ⋮ → "Tillad begrænsede
   indstillinger"). On PC: close the old app (tray icon → Afslut) before starting the new exe.

## Open question from Lennart
He asked "Hvor er versionen af aben henne hvor det hele virkede". The monkey is in every
release since v1.1.0 (screenshots confirmed in v1.1.5). If he still doesn't see it, likely the
old app was still running or the window started hidden in the tray. Ask for a screenshot.
