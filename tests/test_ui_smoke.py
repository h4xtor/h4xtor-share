from __future__ import annotations

import contextlib
import os

import pytest

# Force an isolated config directory so the UI never touches the user's data.
os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/h4xtor-ui-test-smoke")


def _can_build_ui() -> bool:
    try:
        from h4xtor_share.app import H4xtorShareApp

        app = H4xtorShareApp(enable_tray=False)
    except Exception:
        # No display server, missing Tk runtime or tkdnd library: skip.
        return False
    with contextlib.suppress(Exception):
        app.close()
    return True


def _new_app():
    """Build the app; skip when the CI runner's Tk install is broken (seen on Windows)."""
    import tkinter

    from h4xtor_share.app import H4xtorShareApp

    try:
        return H4xtorShareApp(enable_tray=False)
    except tkinter.TclError as error:
        pytest.skip(f"Tk runtime unavailable on this runner: {error}".splitlines()[0])


@pytest.mark.skipif(
    not _can_build_ui(),
    reason="Tk/tkdnd display server unavailable",
)
def test_ui_smoke_builds_and_shows_peer_state() -> None:
    from h4xtor_share.models import Peer, PeerStatus, TransferProgress

    app = _new_app()
    try:
        peer = Peer(
            device_id="ab" * 16,
            name="SmokePeer",
            address="192.168.1.50",
            port=47474,
            fingerprint="cd" * 32,
            platform="linux",
        )
        app.peers[peer.device_id] = peer
        app._upsert_peer(peer)
        app._update_peer_status(PeerStatus(peer.device_id, online=True, rtt_ms=8.0))
        app._update_transfer(
            TransferProgress(
                transfer_id="e" * 32,
                file_name="movie.mp4",
                sent=500,
                total=1000,
                direction="send",
            )
        )
        app.update_idletasks()
        app.update()
        assert peer.device_id in app.device_cards
        assert app.transfer_bars
        assert app.history.devices()
        for page in ("transfers", "clipboard", "history", "settings", "share"):
            app.show_page(page)
            app.update()
    finally:
        app.close()


@pytest.mark.skipif(
    not _can_build_ui(),
    reason="Tk/tkdnd display server unavailable",
)
def test_stale_duplicates_and_removal() -> None:
    from h4xtor_share.models import Peer, PeerStatus

    app = _new_app()
    try:
        current = Peer("11" * 16, "SM-S928B", "192.168.0.190", 47474, "aa" * 32, "android")
        stale = Peer("22" * 16, "S24 Ultra", "192.168.0.190", 47474, "bb" * 32, "android")
        app.config_store.trust_outbound_peer(current.device_id, "t" * 40, "aa" * 32, "SM")
        app._upsert_peer(stale)
        assert stale.device_id in app.device_cards
        app._upsert_peer(current)
        assert stale.device_id not in app.device_cards  # untrusted duplicate dropped
        app._update_peer_status(PeerStatus(current.device_id, True, 5.0))
        app._upsert_peer(stale)
        assert stale.device_id not in app.device_cards  # stale record ignored

        lonely = Peer("33" * 16, "Old laptop", "192.168.0.50", 47474, "cc" * 32, "windows")
        app._upsert_peer(lonely)
        for _ in range(3):
            app._update_peer_status(PeerStatus(lonely.device_id, False, None))
        assert lonely.device_id not in app.device_cards  # unpaired + silent = gone

        other = Peer("44" * 16, "Tablet", "192.168.0.60", 47474, "dd" * 32, "android")
        app._upsert_peer(other)
        app.remove_device(other)
        assert other.device_id not in app.device_cards
        app._upsert_peer(other)
        assert other.device_id not in app.device_cards  # stays hidden
        app.update()
    finally:
        app.close()
