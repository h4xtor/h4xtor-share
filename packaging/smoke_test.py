"""Smoke test for the frozen Windows executable: python packaging/smoke_test.py dist/<exe>.

It must stay up, and later launches (Explorer starts one per selected file) must hand
their files to it and exit instead of opening another window.
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

exe = sys.argv[1]
app = subprocess.Popen([exe, "--minimized"])
time.sleep(12)
if app.poll() is not None:
    sys.exit(f"executable exited early with code {app.poll()}")
try:
    sample = Path(tempfile.mkdtemp()) / "smoke.txt"
    sample.write_text("smoke", encoding="utf-8")
    later = [subprocess.Popen([exe, "--send", str(sample)]) for _ in range(2)]
    for launch in later:
        try:
            code = launch.wait(timeout=30)
        except subprocess.TimeoutExpired:
            launch.kill()
            sys.exit("a second launch kept running instead of handing over to the app")
        if code != 0:
            sys.exit(f"a second launch exited with code {code}")
    if app.poll() is not None:
        sys.exit("the running app died when a second launch handed over")
finally:
    app.kill()
print("frozen executable stayed up and later launches handed over")
