from __future__ import annotations

import hashlib
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from aiohttp import web

from h4xtor_share import __version__, updater
from h4xtor_share.config import Config
from h4xtor_share.updater import UpdateError, Updater

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = """# Opdateringslog

## 9.10.0 – 2030-02-01
### Nyt
- Ti
### Rettet
- Fejl B
  fortsat

## 9.9.9 – 2030-01-01
### Forbedret
- Ni

## 0.0.1 – 2020-01-01
### Nyt
- Gammel
"""


def test_versions_compare_numerically() -> None:
    assert updater.is_newer("1.10.0", "1.9.9")
    assert updater.is_newer("v1.2.1", "1.2.0")
    assert not updater.is_newer("1.2.0", "v1.2.0")
    assert not updater.is_newer("1.2", "1.2.0")
    assert not updater.is_newer("1.9.9", "1.10.0")


def test_changelog_parse_and_aggregate() -> None:
    entries = updater.parse_changelog(CHANGELOG)
    assert [entry.version for entry in entries] == ["9.10.0", "9.9.9", "0.0.1"]
    assert entries[0].sections == {"Nyt": ["Ti"], "Rettet": ["Fejl B fortsat"]}
    skipped = updater.entries_between(entries, "0.0.1", "9.10.0")
    assert [entry.version for entry in skipped] == ["9.10.0", "9.9.9"]  # newest first
    assert "Version 9.10.0  ·  2030-02-01" in skipped[0].text()
    assert updater.release_notes(CHANGELOG, "9.9.9") == "### Forbedret\n- Ni\n"
    with pytest.raises(UpdateError):
        updater.release_notes(CHANGELOG, "1.0.0")


def test_repo_changelog_has_this_version() -> None:
    # CI fails when a release forgets its changelog entry.
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert updater.release_notes(text, __version__).strip()


def test_skip_and_later_are_remembered(tmp_path: Path) -> None:
    config = Config(tmp_path / "config.json")
    up = Updater(config)
    assert up.due(now=1_000_000)
    assert up.should_prompt("9.0.0", now=0)
    up.later("9.0.0", now=0)
    assert not up.should_prompt("9.0.0", now=60)  # "Senere" does not ask again right away
    assert up.should_prompt("9.0.0", now=updater.LATER_DELAY + 1)
    up.skip("9.0.0")
    reloaded = Updater(Config(tmp_path / "config.json"))
    assert not reloaded.should_prompt("9.0.0", now=10**10)  # survives a restart
    assert reloaded.should_prompt("9.0.1", now=0)
    reloaded.auto = False
    assert not reloaded.due(now=10**10)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def release_server():
    """A local stand-in for GitHub Releases; nothing real is downloaded in CI."""
    state: dict = {"payload": b"new exe bytes", "checksum": None, "changelog": CHANGELOG}
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    prefix = f"{base}/h4xtor/h4xtor-share/releases/download/"

    async def latest(_request: web.Request) -> web.Response:
        assets = [{"name": "h4xtor-share-windows.exe"}, {"name": "h4xtor-share-windows.exe.sha256"}]
        if state["changelog"] is not None:
            assets.append({"name": "CHANGELOG.md"})
        for asset in assets:
            asset["browser_download_url"] = f"{prefix}v9.10.0/{asset['name']}"
        assets.append({"name": "evil.exe", "browser_download_url": "http://evil.example/x"})
        return web.json_response(
            {"tag_name": "v9.10.0", "published_at": "2030-02-01T10:00:00Z", "assets": assets}
        )

    async def asset(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if name == "CHANGELOG.md":
            return web.Response(text=state["changelog"])
        if name.endswith(".sha256"):
            digest = state["checksum"] or hashlib.sha256(state["payload"]).hexdigest()
            return web.Response(text=f"{digest}  h4xtor-share-windows.exe\n")
        return web.Response(body=state["payload"])

    app = web.Application()
    app.router.add_get("/repos/h4xtor/h4xtor-share/releases/latest", latest)
    app.router.add_get("/h4xtor/h4xtor-share/releases/download/{tag}/{name}", asset)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    try:
        yield state, f"{base}/repos/h4xtor/h4xtor-share/releases/latest", prefix
    finally:
        await runner.cleanup()


async def test_check_download_and_checksum(release_server, tmp_path: Path) -> None:
    state, api, prefix = release_server
    up = Updater(Config(tmp_path / "config.json"), api_url=api, download_prefix=prefix)
    found = await up.check()
    assert found is not None
    release, entries = found
    assert release.version == "9.10.0" and "evil.exe" not in release.assets
    assert [entry.version for entry in entries][:2] == ["9.10.0", "9.9.9"]
    assert not up.due()  # checked just now
    assert "9.10.0" in (tmp_path / "changelog.md").read_text(encoding="utf-8")  # offline log

    seen: list[tuple[int, int]] = []
    path = await up.download(
        release, tmp_path / "dl", lambda done, total: seen.append((done, total))
    )
    assert path.read_bytes() == state["payload"] and seen

    state["checksum"] = "0" * 64
    with pytest.raises(UpdateError, match="Tjeksummen passer ikke"):
        await up.download(release, tmp_path / "bad")
    assert not any((tmp_path / "bad").iterdir())  # the bad file is gone


async def test_missing_changelog_does_not_block(release_server, tmp_path: Path) -> None:
    state, api, prefix = release_server
    state["changelog"] = None
    up = Updater(Config(tmp_path / "config.json"), api_url=api, download_prefix=prefix)
    found = await up.check()
    assert found is not None  # still offered; the dialog says "Ingen nyhedsliste tilgængelig"


async def test_offline_check_fails_quietly(tmp_path: Path) -> None:
    up = Updater(
        Config(tmp_path / "config.json"),
        api_url=f"http://127.0.0.1:{_free_port()}/nothing",
        download_prefix="http://127.0.0.1/",
        timeout=2,
    )
    with pytest.raises(Exception):  # noqa: B017 - the app's automatic check swallows this
        await up.check()


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_pc_update_swaps_and_confirms(tmp_path: Path) -> None:
    folder = tmp_path / "config"
    folder.mkdir()
    target = _script(tmp_path, "app.py", "old")
    new = _script(
        tmp_path,
        "new.py",
        f"from pathlib import Path\nPath({str(folder)!r}, 'update-ok').write_text('x')\n",
    )

    def launch(path: Path):
        return subprocess.Popen([sys.executable, str(path)])

    assert updater.apply_update(new, target, 0, folder, launch=launch, timeout=20)
    assert "update-ok" in target.read_text(encoding="utf-8")  # the new version is in place
    assert not target.with_name("app.py.old").exists() and not new.exists()
    assert updater.mark_started(folder) is None


def test_pc_update_rolls_back_when_new_version_fails(tmp_path: Path) -> None:
    folder = tmp_path / "config"
    folder.mkdir()
    target = _script(tmp_path, "app.py", "import sys\n")
    new = _script(tmp_path, "new.py", "raise SystemExit(3)\n")
    launched: list[str] = []

    def launch(path: Path):
        launched.append(path.read_text(encoding="utf-8"))
        return subprocess.Popen([sys.executable, str(path)])

    assert not updater.apply_update(new, target, 0, folder, launch=launch, timeout=20)
    assert target.read_text(encoding="utf-8") == "import sys\n"  # old version restored
    assert launched == ["raise SystemExit(3)\n", "import sys\n"]  # and started again
    assert "sat tilbage" in (updater.mark_started(folder) or "")
    assert updater.mark_started(folder) is None  # the note is shown once


def test_android_version_matches() -> None:
    gradle = (ROOT / "android" / "app" / "build.gradle").read_text(encoding="utf-8")
    assert f"?: '{__version__}'" in gradle  # versionName == the desktop version


def test_pc_update_rolls_back_when_new_version_hangs(tmp_path: Path) -> None:
    folder = tmp_path / "config"
    folder.mkdir()
    target = _script(tmp_path, "app.py", "import sys\n")
    new = _script(tmp_path, "new.py", "import time\ntime.sleep(60)\n")  # never says "update-ok"
    started: list = []

    def launch(path: Path):
        started.append(subprocess.Popen([sys.executable, str(path)]))
        return started[-1]

    assert not updater.apply_update(new, target, 0, folder, launch=launch, timeout=2)
    assert started[0].poll() is not None  # the hung new version was stopped
    assert target.read_text(encoding="utf-8") == "import sys\n"  # old version restored
    assert "sat tilbage" in (updater.mark_started(folder) or "")
