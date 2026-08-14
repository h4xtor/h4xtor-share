from __future__ import annotations

import contextlib
import os

import pytest

# Force an isolated config directory so the UI never touches the user's data.
os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/h4xtor-ui-test-smoke")


def _can_build_ui() -> bool:
    try:
        from h4xtor_share.app import H4xtorShareApp

        app = H4xtorShareApp()
    except Exception:
        # No display server, missing Tk runtime or tkdnd library: skip.
        return False
    with contextlib.suppress(Exception):
        app.close()
    return True


@pytest.mark.skipif(
    not _can_build_ui(),
    reason="Tk/tkdnd display server unavailable",
)
def test_ui_smoke_builds_and_shows_peer_state() -> None:
    from h4xtor_share.app import H4xtorShareApp
    from h4xtor_share.models import Peer, PeerStatus, TransferProgress

    app = H4xtorShareApp()
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
        assert app.peer_tree.exists(peer.device_id)
        assert app.transfer_bars
        assert app.history.devices()
    finally:
        app.close()
