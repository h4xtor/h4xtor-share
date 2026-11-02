# h4xtor-share — UI redesign handover (2026-10-28)

Handover for continuing the UI overhaul in a fresh Claude Code session working in
`h4xtor/h4xtor-share` (branch `main`). Nothing in the app code has changed yet — only a
design proposal (mockup) was approved and the "taste" skills were installed locally.

## Owner & working style (read `CLAUDE.md` too)
- Talk to Lennart in **Danish**, warm, short, plain language. He does **not** code — never paste code in chat.
- **Test everything before handing over** (design + every function). Render the Tk app headless and screenshot it.
- GitHub is the source of truth; push when an update is done. Local folder: `C:\Users\Lenna\Desktop\h4xtorshare`.
- Currently on **v1.7.0**.

## The decision (APPROVED)
Move the whole app away from the "spacey" Battle.net / Aurora-glass look to a clean **IDE look**
like Lennart's own "Lennart Notepad" app.

**Keep h4xtor's ORIGINAL colours** — blue accent (`#148EFF`), charcoal background, green ONLY for
online status (`#3CCB7F`). **Do NOT** use a green accent (an earlier green mockup was rejected).

Apply the **new menu grouping/layout** from the approved mockup:
- Flat, de-spaced page headers: small **monospace eyebrow** + title + subtitle. No glow, no embers, no light rays.
- **Top bar**: logo + version badge + breadcrumb on the left; status pills (● Online, Wi‑Fi Direct) on the right.
- **Tabs** row under the top bar for the current group.
- **Right rail** on the Send page: the monkey in a small mascot card + a "Seneste" (recent) list.
- **Bottom status bar**: segmented, monospace — `● Online · Wi‑Fi Direct · Bluetooth · 3 enheder · :47474 · TLS pinned · UTF‑8 · v1.7.0`.
- Flatten the glass gloss (hairline borders, flat cards). Keep rounded corners, but subtle.
- **Keep the monkey mascot** — clean up the vector graphics and make the animations **better/funnier**.

**(?) help on every button**: a small circular `?` marker next to each button that, on hover/focus,
shows a tooltip with a **detailed** explanation of what the button does. Exception: self-explanatory
ones like "Forbind ny enhed" get none.

**Android APK must be adapted to the same look** (`android/.../com/h4xtor/share/Ui.java` design tokens,
`LauncherBackdrop`/`HeroArt`, the card/button styles and the layouts). Phone and PC should look like siblings.

## Where things live (design layer)
- `src/h4xtor_share/ui_kit.py` — `Theme` (LIGHT/DARK palettes), `Button`, `Card`, `Toggle`, `Pill`,
  `DeviceTiles`, `MonkeyActor` + `monkey_parts`/`draw_monkey`, `HeroBanner` (the big spacey key-art — replace
  with a flat header, keep the public API: `.buttons`, `.set_words`, `.refresh_buttons`, `.actor`, `.burst`),
  `render_backdrop` (the glow/ray/ember art — remove from use), `glass_image` (lower the `light`/shine),
  `tooltip` (extend into a richer title+body tooltip and add a `help_dot(...)` factory for the `?` marker).
- `src/h4xtor_share/app.py` — `_build_ui` (add top bar; restyle bottom status bar), `_build_sidebar`,
  `_page` (flatten: drop `_header_art`/`render_backdrop`, use flat eyebrow+title), `_build_share_page`
  (swap hero → flat header; keep device tiles but flatten; add right rail; add `?` help on the Filer/Mappe/
  Udklipsholder/Vælg modtager/Send buttons), and the other `_build_*_page` methods for help markers.
- `src/h4xtor_share/__init__.py`, `pyproject.toml`, `android/app/build.gradle` — version bump on release.
- `CHANGELOG.md` — add a `## X.Y.Z – YYYY-MM-DD` entry with `### Nyt/Forbedret/Rettet` (apps parse it; release fails without it).

## Approved mockup & before/after
A faithful HTML mockup of the target was approved (blue palette, IDE layout, `?` help, right-rail monkey).
Reference assets produced this session (in the Claude container, not committed):
- `/home/claude/shots/before_share.png` — current "spacey" look.
- `/home/claude/shots/after_share.png` — approved target look (blue).
- `/home/claude/shots/after.html` — the mockup source (useful as a pixel reference for spacing/typography).
Lennart's own reference screenshot was his "Lennart Notepad v1.1.0" app (dark IDE: left file/section sidebar,
top tabs, main area, right assistant panel, bottom status strip, one accent colour, monospace in places).

## Decided design tokens (dark)
bg `#111318` · sidebar `#0B0D11` · chrome `#08090C` · card `#1A1D24` · card_hover `#22262F` ·
border `#272B34` · border_strong `#363B46` · text `#F3F5F9` · muted `#AAB1BE` · faint `#8A92A0` ·
accent `#148EFF` · accent_hover `#3BA2FF` · online/success `#3CCB7F` · warning `#F2B33D` · danger `#FF6B6B`.
Monospace for labels/eyebrows/status/version badges. UI font: the existing Segoe UI stack.

## Taste skills (use them, don't skip)
Installed locally under `.claude/skills/` (git-excluded, not part of the product):
`bencium-impact-designer`, `design-audit`, `typography`, `bencium-controlled-ux-designer`, `ui-ux-pro-max`.
Core rule from them: avoid "AI slop" — no glass morphism, no generic SaaS-blue-on-white, no blobs/liquid.
Commit to one clear direction (here: a crisp dark developer-tool / IDE aesthetic). `ui-ux-pro-max` has a
search CLI: `python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<q>" --domain style|color|typography`.

## Dev / test (Linux container)
tkinter needs Python 3.12 (the 3.13 build has no tkinter). Set up once:
```
apt-get install -y python3-tk tk xvfb imagemagick
python3.12 -m venv /home/claude/venv && /home/claude/venv/bin/pip install -e .
```
Render + screenshot a page headless:
```
xvfb-run -a -s "-screen 0 1180x760x24" /home/claude/venv/bin/python shots/shoot_before.py
```
(`shots/shoot_before.py` instantiates `H4xtorShareApp(enable_tray=False)`, calls `show_page(name)`,
pumps the event loop ~2s, then `import -window root before_<name>.png`.)
Checks: `ruff check .` and `pytest -q` (Tk tests need a display: `xvfb-run -a pytest -q`).
Android build is CI-only (`.github/workflows/ci.yml`); can't run an emulator in the container.

## Also on the task list (from the kravliste — verify while here)
- Error/feature sweep against the kravliste: Join parity (notification mirroring + reply, SMS from PC,
  on-demand screenshot, find-my-phone/remote, send-to-all), Wi‑Fi Direct 100% on APK + EXE (EXE also
  creates the network), transfer controls in the APK (stop all / start individually / clearer status),
  in-app auto-update on APK + EXE with a visible changelog, optional Google Drive OAuth button.
- Keep each new feature's on/off switch, a test, and the new flat look on both sides.

## Status at handover
- Repo cloned, deps installed, current design rendered (before/after screenshots done).
- Taste skills installed locally. Memory/project updated with the decision.
- **No app code changed yet.** Next step: implement the flat IDE look in `ui_kit.py` + `app.py`, render to
  verify, then adapt the Android `Ui`, then the `?` help everywhere, then the error/feature sweep, then
  bump version + CHANGELOG, commit and push.
