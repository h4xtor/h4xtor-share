"""Cross-platform opening and execution of received files.

``open_path`` is the single entry point used by the UI.  On every platform it
falls back to the OS file association (``xdg-open``/``open``/``startfile``);
on Linux it additionally makes the target executable first so shell scripts and
binaries run directly, matching the behavior users expect for received files.
"""

from __future__ import annotations

import contextlib
import os
import platform
import subprocess
from pathlib import Path

_IS_WINDOWS = platform.system() == "Windows"
_IS_MACOS = platform.system() == "Darwin"


def make_executable(path: Path) -> None:
    """Set the owner-executable bit on *path* (no-op on Windows)."""
    if _IS_WINDOWS:
        return
    with contextlib.suppress(OSError):
        path.chmod(path.stat().st_mode | 0o111)


def _start_detached(command: list[str]) -> None:
    flags = 0
    if _IS_WINDOWS:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(  # noqa: S603 - trusted local files chosen by the user
        command,
        start_new_session=not _IS_WINDOWS,
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def _open_linux(path: Path) -> None:
    if path.suffix.lower() in {".exe", ".msi", ".apk"}:
        raise RuntimeError(
            f"{path.suffix} cannot be executed natively on Linux; "
            "copy it to the target operating system instead."
        )
    make_executable(path)
    _start_detached(["xdg-open", str(path)])


def _open_windows(path: Path) -> None:
    os.startfile(str(path))  # noqa: S606 - Windows-only file association open


def _open_macos(path: Path) -> None:
    make_executable(path)
    _start_detached(["open", str(path)])


def open_path(path: str | Path) -> None:
    """Open or execute *path* using the platform's native mechanism."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    if _IS_WINDOWS:
        _open_windows(resolved)
    elif _IS_MACOS:
        _open_macos(resolved)
    else:
        _open_linux(resolved)


def reveal_in_folder(path: str | Path) -> None:
    """Open the folder containing *path* with the file selected where possible."""
    resolved = Path(path).expanduser().resolve()
    if _IS_WINDOWS:
        # Always go through explorer.exe: ShellExecute on a folder uses whatever
        # verb is registered as default, which other apps can hijack.
        if resolved.is_dir():
            _start_detached(["explorer.exe", str(resolved)])
        else:
            _start_detached(["explorer.exe", f"/select,{resolved}"])
    elif _IS_MACOS:
        if resolved.is_dir():
            _start_detached(["open", str(resolved)])
        else:
            _start_detached(["open", "-R", str(resolved)])
    else:
        _start_detached(["xdg-open", str(resolved if resolved.is_dir() else resolved.parent)])
