"""Automatic updates – only from GitHub Releases of h4xtor/h4xtor-share, only over HTTPS.

Purely local to this device: nothing here is announced on the device protocol or
touches pairing, certificates or settings.

Flow: check (at most once a day, silent when offline) → ask with the changelog →
download to a temp folder → verify the release's SHA-256 file → on the Windows
.exe a helper copy of this exe swaps the file, starts the new version, and puts
the old one back if the new one does not come up.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

from h4xtor_share import __version__
from h4xtor_share.config import Config

REPO = "h4xtor/h4xtor-share"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
CHANGELOG_ASSET = "CHANGELOG.md"
WINDOWS_ASSET = "h4xtor-share-windows.exe"
CHECK_INTERVAL = 24 * 3600
LATER_DELAY = 24 * 3600
SECTIONS = ("Nyt", "Forbedret", "Rettet")
OK_MARKER = "update-ok"
FAILED_NOTE = "update-failed"
NO_CHANGELOG = "Ingen nyhedsliste tilgængelig."

_HEADING = re.compile(r"^##\s+v?(\d+(?:\.\d+)+)\s*[–—-]\s*(\d{4}-\d{2}-\d{2})\s*$")
_SECTION = re.compile(r"^###\s+(.+?)\s*$")


class UpdateError(Exception):
    """A clear, user-facing reason why an update stopped."""


# -- versions -------------------------------------------------------------------
def version_tuple(value: str) -> tuple[int, ...]:
    numbers = []
    for piece in value.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        numbers.append(int(digits or 0))
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()  # 1.2 == 1.2.0
    return tuple(numbers)


def is_newer(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


# -- changelog ------------------------------------------------------------------
@dataclass
class ChangelogEntry:
    version: str
    date: str
    sections: dict[str, list[str]] = field(default_factory=dict)

    def text(self) -> str:
        lines = [f"Version {self.version}  ·  {self.date}"]
        for name in SECTIONS:
            items = self.sections.get(name) or []
            if items:
                lines.append(f"\n{name}")
                lines.extend(f"  •  {item}" for item in items)
        return "\n".join(lines)


def parse_changelog(text: str) -> list[ChangelogEntry]:
    """Parse "## 1.2.3 – 2026-10-14" entries with "### Nyt/Forbedret/Rettet" lists."""
    entries: list[ChangelogEntry] = []
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if heading := _HEADING.match(line):
            entries.append(ChangelogEntry(heading.group(1), heading.group(2)))
            section = None
        elif entries and (match := _SECTION.match(line)):
            section = match.group(1) if match.group(1) in SECTIONS else None
        elif entries and section and line.startswith(("- ", "* ")):
            entries[-1].sections.setdefault(section, []).append(line[2:].strip())
    entries.sort(key=lambda entry: version_tuple(entry.version), reverse=True)
    return entries


def entries_between(
    entries: list[ChangelogEntry], current: str, latest: str
) -> list[ChangelogEntry]:
    """Everything newer than ``current`` up to ``latest``, newest first."""
    return [
        entry
        for entry in entries
        if is_newer(entry.version, current) and not is_newer(entry.version, latest)
    ]


def release_notes(text: str, version: str) -> str:
    """Markdown body for the GitHub release; fails when the version has no entry."""
    for entry in parse_changelog(text):
        if version_tuple(entry.version) == version_tuple(version):
            parts = []
            for name in SECTIONS:
                if entry.sections.get(name):
                    parts.append(
                        f"### {name}\n" + "\n".join(f"- {i}" for i in entry.sections[name])
                    )
            if parts:
                return "\n\n".join(parts) + "\n"
            raise UpdateError(f"CHANGELOG.md: version {version} har ingen punkter.")
    raise UpdateError(f"CHANGELOG.md mangler en sektion for version {version}.")


# -- the updater ------------------------------------------------------------------
@dataclass
class Release:
    version: str
    date: str
    page_url: str
    assets: dict[str, str]


class Updater:
    def __init__(
        self,
        config: Config,
        api_url: str = API_URL,
        download_prefix: str = DOWNLOAD_PREFIX,
        asset: str = WINDOWS_ASSET,
        timeout: float = 10.0,
    ) -> None:
        self.config = config
        self.api_url = api_url
        self.download_prefix = download_prefix
        self.asset = asset
        self.timeout = timeout

    @property
    def folder(self) -> Path:
        return self.config.path.parent

    # -- settings --------------------------------------------------------------
    @property
    def auto(self) -> bool:
        return bool(self.config.data.get("update_auto", True))

    @auto.setter
    def auto(self, value: bool) -> None:
        self._save(update_auto=bool(value))

    def due(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        last = float(self.config.data.get("update_last_check") or 0)
        return self.auto and now - last >= CHECK_INTERVAL

    def should_prompt(self, version: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        data = self.config.data
        if data.get("update_skip") == version:
            return False
        return not (
            data.get("update_later") == version and now < float(data.get("update_later_until") or 0)
        )

    def skip(self, version: str) -> None:
        self._save(update_skip=version)

    def later(self, version: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._save(update_later=version, update_later_until=now + LATER_DELAY)

    def _save(self, **values: Any) -> None:
        self.config.data.update(values)
        with contextlib.suppress(OSError):
            self.config.save()

    # -- changelog cache --------------------------------------------------------
    def changelog_text(self) -> str:
        """The newest changelog we know: downloaded copy, else the one shipped with the app."""
        here = Path(__file__).resolve().parent
        best, best_version = "", ()
        # Downloaded copy, the one shipped in the exe, or the repo's own (source checkout).
        for path in (
            self.folder / "changelog.md",
            here / CHANGELOG_ASSET,
            here.parents[1] / CHANGELOG_ASSET,
        ):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            entries = parse_changelog(text)
            if entries and version_tuple(entries[0].version) > best_version:
                best, best_version = text, version_tuple(entries[0].version)
        return best

    def changelog(self) -> list[ChangelogEntry]:
        return parse_changelog(self.changelog_text())

    # -- network ----------------------------------------------------------------
    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=self.timeout, sock_read=60),
            trust_env=True,
            headers={"User-Agent": f"h4xtor-share/{__version__}"},
        )

    def _checked(self, response: aiohttp.ClientResponse) -> None:
        # Redirects (GitHub → its download CDN) must stay on HTTPS.
        if self.download_prefix.startswith("https://") and response.url.scheme != "https":
            raise UpdateError("Opdateringen blev stoppet: forbindelsen var ikke krypteret.")
        if response.status != 200:
            raise UpdateError(f"GitHub svarede {response.status}.")

    async def check(self) -> tuple[Release, list[ChangelogEntry]] | None:
        """The newest release and what changed since this version; None when up to date.

        Raises UpdateError/aiohttp errors when GitHub cannot be reached; automatic
        checks swallow those so being offline stays silent.
        """
        self._save(update_last_check=time.time())
        async with self._session() as session:
            async with session.get(
                self.api_url, headers={"Accept": "application/vnd.github+json"}
            ) as response:
                self._checked(response)
                payload = await response.json()
            if payload.get("draft") or payload.get("prerelease"):
                return None
            version = str(payload.get("tag_name") or "").lstrip("vV")
            assets = {
                str(asset.get("name")): str(asset.get("browser_download_url") or "")
                for asset in payload.get("assets") or []
                if str(asset.get("browser_download_url") or "").startswith(self.download_prefix)
            }
            release = Release(
                version,
                str(payload.get("published_at") or "")[:10],
                f"https://github.com/{REPO}/releases/tag/v{version}",
                assets,
            )
            if CHANGELOG_ASSET in assets:
                with contextlib.suppress(Exception):
                    text = await self._text(session, assets[CHANGELOG_ASSET])
                    if parse_changelog(text):
                        (self.folder / "changelog.md").write_text(text, encoding="utf-8")
        if not version or not is_newer(version, __version__):
            return None
        return release, entries_between(self.changelog(), __version__, version)

    async def _text(self, session: aiohttp.ClientSession, url: str) -> str:
        async with session.get(url) as response:
            self._checked(response)
            return await response.text()

    async def download(
        self,
        release: Release,
        folder: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Fetch the installer and verify it against the release's .sha256 file."""
        url = release.assets.get(self.asset)
        checksum_url = release.assets.get(f"{self.asset}.sha256")
        if not url or not checksum_url:
            raise UpdateError(
                "Udgivelsen mangler filen eller dens tjeksum – opdateringen er stoppet."
            )
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{release.version}-{self.asset}"
        partial = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        try:
            async with self._session() as session:
                expected = (await self._text(session, checksum_url)).split()[0].lower()
                if not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise UpdateError("Tjeksum-filen er ugyldig – opdateringen er stoppet.")
                async with session.get(url) as response:
                    self._checked(response)
                    total = int(response.headers.get("Content-Length") or 0)
                    done = 0
                    with partial.open("wb") as output:
                        async for chunk in response.content.iter_chunked(256 * 1024):
                            output.write(chunk)
                            digest.update(chunk)
                            done += len(chunk)
                            if progress:
                                progress(done, total)
            if digest.hexdigest() != expected:
                raise UpdateError(
                    "Tjeksummen passer ikke – filen er slettet, og intet er ændret. "
                    "Prøv igen senere."
                )
            partial.replace(target)
        finally:
            with contextlib.suppress(OSError):
                partial.unlink(missing_ok=True)
        return target


# -- installing on Windows (.exe) -------------------------------------------------
def can_self_install() -> bool:
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def start_helper(new_exe: Path, folder: Path) -> None:
    """Run a copy of this exe that swaps in ``new_exe`` once this process has exited."""
    current = Path(sys.executable)
    helper = new_exe.with_name("h4xtor-share-updater.exe")
    shutil.copy2(current, helper)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(  # noqa: S603 - our own exe with our own arguments
        [str(helper), "--apply-update", str(new_exe), str(current), str(os.getpid()), str(folder)],
        creationflags=flags,
        close_fds=True,
    )


def _wait_for_exit(pid: int, timeout: float) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if handle:
            kernel.WaitForSingleObject(handle, int(timeout * 1000))
            kernel.CloseHandle(handle)
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)


def _launch(path: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen([str(path)], close_fds=True)  # noqa: S603


def apply_update(
    new: Path,
    target: Path,
    pid: int,
    folder: Path,
    launch: Callable[[Path], Any] = _launch,
    timeout: float = 120.0,
) -> bool:
    """Swap ``target`` for ``new``, start it, and roll back if it does not come up.

    The new app proves it started by writing ``folder/update-ok``. Settings,
    pairings and certificates live in ``folder`` and are never touched.
    """
    _wait_for_exit(pid, 30)
    backup = target.with_name(target.name + ".old")
    marker = folder / OK_MARKER
    with contextlib.suppress(OSError):
        marker.unlink(missing_ok=True)
    deadline = time.monotonic() + 30
    while True:  # the exe stays locked until the old process is fully gone
        try:
            backup.unlink(missing_ok=True)
            target.replace(backup)
            break
        except OSError:
            if time.monotonic() > deadline:
                _note(folder, "Den gamle version kunne ikke lukkes – intet er ændret.")
                launch(target)
                return False
            time.sleep(0.5)
    try:
        shutil.copy2(new, target)
        process = launch(target)
    except OSError:
        process = None
    end = time.monotonic() + timeout
    while process is not None and time.monotonic() < end and not marker.exists():
        if process.poll() is not None:
            break  # died before it was up
        time.sleep(0.25)
    if marker.exists():  # only the new app's own "I'm up" counts as success
        for path in (new, backup):
            with contextlib.suppress(OSError):
                path.unlink()
        return True
    if process is not None and process.poll() is None:  # hung while starting
        _stop(process)
    deadline = time.monotonic() + 30
    while True:  # a just-stopped exe can stay locked for a moment
        try:
            target.unlink(missing_ok=True)
            backup.replace(target)
            break
        except OSError:
            if time.monotonic() > deadline:
                _note(
                    folder,
                    "Den nye version startede ikke. Den tidligere ligger som "
                    f"{backup.name} ved siden af – omdøb den til {target.name}.",
                )
                return False
            time.sleep(0.5)
    _note(folder, "Den nye version kunne ikke starte – din tidligere version er sat tilbage.")
    launch(target)
    return False


def _stop(process: Any) -> None:
    if os.name == "nt":  # the one-file exe is a launcher plus a child: end both
        subprocess.run(  # noqa: S603
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],  # noqa: S607
            capture_output=True,
            check=False,
        )
    with contextlib.suppress(OSError):
        process.kill()
    with contextlib.suppress(Exception):
        process.wait(timeout=10)


def _note(folder: Path, text: str) -> None:
    with contextlib.suppress(OSError):
        (folder / FAILED_NOTE).write_text(text, encoding="utf-8")


def run_helper(arguments: list[str]) -> bool:
    """Entry for ``h4xtor-share.exe --apply-update NEW TARGET PID FOLDER``."""
    new, target, pid, folder = arguments[:4]
    return apply_update(Path(new), Path(target), int(pid), Path(folder))


def mark_started(folder: Path) -> str | None:
    """Called by the app once it is up: confirms an update, returns a rollback note."""
    with contextlib.suppress(OSError):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / OK_MARKER).write_text(__version__, encoding="utf-8")
    note = folder / FAILED_NOTE
    try:
        text = note.read_text(encoding="utf-8")
    except OSError:
        return None
    with contextlib.suppress(OSError):
        note.unlink()
    return text


if __name__ == "__main__":  # CI: python -m h4xtor_share.updater notes 1.3.0 CHANGELOG.md
    if sys.argv[1:2] == ["notes"]:
        try:
            print(release_notes(Path(sys.argv[3]).read_text(encoding="utf-8"), sys.argv[2]), end="")
        except UpdateError as error:
            sys.exit(str(error))
