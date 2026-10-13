"""Smoke test for the frozen Windows updater: python packaging/update_smoke.py dist/<exe>.

Installs a copy of the exe in a temp folder, runs the real update helper on it the way
the app does ("--apply-update"), and checks that the new copy took its place, started
(it confirms with "update-ok") and that the backup was cleaned up.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from platformdirs import user_config_dir

exe = Path(sys.argv[1]).resolve()
work = Path(tempfile.mkdtemp())
target = work / "h4xtor-share.exe"
new = work / "downloaded.exe"
helper = work / "h4xtor-share-updater.exe"
for path in (target, new, helper):
    shutil.copy2(exe, path)
folder = Path(user_config_dir("h4xtor-share"))
(folder / "update-ok").unlink(missing_ok=True)
(folder / "update-failed").unlink(missing_ok=True)


def kill_all() -> None:
    subprocess.run(["taskkill", "/F", "/T", "/IM", "h4xtor-share.exe"], capture_output=True)


kill_all()  # an app still running would take the new copy's launch over
try:
    code = subprocess.run(
        [str(helper), "--apply-update", str(new), str(target), "0", str(folder)], timeout=180
    ).returncode
finally:
    kill_all()
if code != 0:
    note = folder / "update-failed"
    sys.exit(f"update helper failed ({code}): {note.read_text('utf-8') if note.exists() else ''}")
if not target.is_file() or new.exists():
    sys.exit("the new version is not in place")
if target.with_name(target.name + ".old").exists():
    sys.exit("the backup was kept although the new version started")
print("frozen update helper swapped the exe, started it and cleaned up")
