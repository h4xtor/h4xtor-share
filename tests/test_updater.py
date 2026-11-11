from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import threading
import time
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


def _old_app(tmp_path: Path, seconds: float) -> subprocess.Popen:
    """A stand-in for the old app's process: it lives ``seconds`` unless it is ended."""
    script = _script(tmp_path, "old_app.py", f"import time\ntime.sleep({seconds})\n")
    process = subprocess.Popen([sys.executable, str(script)])
    threading.Thread(target=process.wait, daemon=True).start()  # so it is gone once it ends
    return process


def _confirming(tmp_path: Path, folder: Path) -> Path:
    return _script(
        tmp_path,
        "new.py",
        f"from pathlib import Path\nPath({str(folder)!r}, 'update-ok').write_text('x')\n",
    )


def test_pc_update_ends_an_old_app_that_hangs_before_starting_the_new_one(
    tmp_path: Path,
) -> None:
    """The old app has closed its window but its process hangs (a stuck background call):
    it must be gone before the new version starts, or the new one finds the ports taken."""
    folder = tmp_path / "config"
    folder.mkdir()
    target = _script(tmp_path, "app.py", "old")
    new = _confirming(tmp_path, folder)
    old = _old_app(tmp_path, 120)
    seen: list[bool] = []

    def launch(path: Path):
        seen.append(updater._alive(old.pid))  # is the old app still there when we start?
        return subprocess.Popen([sys.executable, str(path)])

    try:
        started = time.monotonic()
        assert updater.apply_update(new, target, old.pid, folder, launch=launch,
                                    timeout=20, grace=1.0)
        assert time.monotonic() - started < 15  # it did not sit out the old app's two minutes
        assert seen == [False]  # the old app was gone before the new one was started
        assert old.poll() is not None
        assert "update-ok" in target.read_text(encoding="utf-8")
        log = (folder / "update.log").read_text(encoding="utf-8")
        assert "lukkede ikke selv" in log and "opdateringen er gennemført" in log
        assert updater.mark_started(folder) is None  # no failure note
    finally:
        if old.poll() is None:
            old.kill()


def test_pc_update_leaves_an_old_app_alone_that_closes_in_time(tmp_path: Path) -> None:
    folder = tmp_path / "config"
    folder.mkdir()
    target = _script(tmp_path, "app.py", "old")
    new = _confirming(tmp_path, folder)
    old = _old_app(tmp_path, 1.0)
    ended: list[int] = []

    def launch(path: Path):
        return subprocess.Popen([sys.executable, str(path)])

    assert updater.apply_update(new, target, old.pid, folder, launch=launch, timeout=20,
                                grace=20.0, end=ended.append)
    assert ended == []  # it left by itself: nothing was ended
    log = (folder / "update.log").read_text(encoding="utf-8")
    assert "den gamle app er lukket" in log and "lukkede ikke selv" not in log


def test_pc_update_changes_nothing_when_the_old_app_cannot_be_ended(
    tmp_path: Path, monkeypatch
) -> None:
    folder = tmp_path / "config"
    folder.mkdir()
    target = _script(tmp_path, "app.py", "old")
    new = _confirming(tmp_path, folder)
    old = _old_app(tmp_path, 120)
    launched: list[Path] = []
    monkeypatch.setattr(updater, "END_WAIT", 0.5)
    try:
        assert not updater.apply_update(new, target, old.pid, folder,
                                        launch=launched.append, timeout=5, grace=0.5,
                                        end=lambda _pid: None)  # ending it does not work
        assert launched == []  # nothing is started on top of an app that is still running
        assert target.read_text(encoding="utf-8") == "old"  # and nothing was swapped
        assert not target.with_name("app.py.old").exists() and new.exists()
        note = updater.mark_started(folder) or ""
        assert "kunne ikke lukkes" in note and "Afslut" in note
    finally:
        old.kill()


def _run(code: str, timeout: float = 30) -> tuple[int, float]:
    started = time.monotonic()
    done = subprocess.run([sys.executable, "-c", code], timeout=timeout, check=False)
    return done.returncode, time.monotonic() - started


def test_leaving_for_an_update_ends_the_process_whatever_still_runs() -> None:
    worker = "import threading, time\nthreading.Thread(target=time.sleep, args=(60,)).start()\n"
    leave = "from h4xtor_share.updater import exit_after, leave_process\n"
    # Closed in order, but a worker thread is stuck: Python alone would wait a minute for it.
    code, seconds = _run(worker + leave + "leave_process(lambda: None)\n")
    assert code == 0 and seconds < 15
    # The orderly close itself hangs: gone after the grace period.
    code, seconds = _run(leave + "import time\nleave_process(lambda: time.sleep(60), grace=1.0)\n")
    assert code == 0 and seconds < 15
    # An ordinary quit: the program ends, a stuck worker gets three seconds at most.
    code, seconds = _run(worker + leave + "exit_after(1.0)\n")
    assert code == 0 and seconds < 15


def test_helper_is_a_fresh_copy_started_as_a_new_instance(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "config"
    folder.mkdir()
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    exe = tmp_path / "h4xtor-share.exe"
    exe.write_bytes(b"the running app")
    new_exe = downloads / "h4xtor-share-windows.exe"
    new_exe.write_bytes(b"the new app")
    stale = downloads / "h4xtor-share-updater.exe"  # left by an earlier update
    stale.write_bytes(b"old helper")
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))

    updater.start_helper(new_exe, folder)
    (args, options), = calls
    helper = Path(args[0])
    assert helper.parent == downloads and helper.read_bytes() == b"the running app"
    assert helper.name == f"h4xtor-share-updater-{os.getpid()}.exe"  # its own name per try
    assert not stale.exists()
    assert args[1:] == ["--apply-update", str(new_exe), str(exe), str(os.getpid()), str(folder)]
    # PyInstaller must unpack the copy as a new start of the app, not as a child of this one.
    assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "hjælper startet" in (folder / "update.log").read_text(encoding="utf-8")

    # It cannot be started (here: the download folder is gone): a clear message, in Danish.
    missing = tmp_path / "gone" / "h4xtor-share-windows.exe"
    with pytest.raises(updater.UpdateError, match="kunne ikke startes"):
        updater.start_helper(missing, folder)
    assert len(calls) == 1


def test_leftovers_of_an_update_are_tidied_and_the_log_stays_small(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    exe = tmp_path / "h4xtor-share.exe"
    exe.write_bytes(b"app")
    previous = tmp_path / "h4xtor-share.exe.old"
    previous.write_bytes(b"previous version")
    helper = downloads / "h4xtor-share-updater-4711.exe"
    helper.write_bytes(b"helper")
    keep = downloads / "h4xtor-share-windows.exe"
    keep.write_bytes(b"download")
    updater.tidy_after_update(exe, downloads)
    assert not previous.exists() and not helper.exists()
    assert exe.exists() and keep.exists()
    updater.tidy_after_update(exe, tmp_path / "missing")  # nothing there: no error

    for number in range(3000):
        updater._log(tmp_path, f"linje {number} " + "x" * 40)
    log = (tmp_path / "update.log").read_text(encoding="utf-8")
    assert len(log) < 80 * 1024 and "linje 2999" in log and "linje 0 " not in log
