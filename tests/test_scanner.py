from __future__ import annotations

import pytest

from h4xtor_share.models import Peer
from h4xtor_share.scanner import cidr_targets, scan_lan, scan_targets


def test_scan_targets_builds_local_24_and_excludes_local_address() -> None:
    targets = scan_targets(["192.168.10.47"])
    assert "192.168.10.47" not in targets
    assert targets[0] == "192.168.10.1"
    assert targets[-1] == "192.168.10.254"
    assert len(targets) == 253


def test_cidr_targets_rejects_overly_broad_ranges() -> None:
    with pytest.raises(ValueError):
        cidr_targets("10.0.0.0/8")


@pytest.mark.asyncio
async def test_scan_lan_returns_only_compatible_peers() -> None:
    class FakeClient:
        async def get_info(self, address: str, port: int, *, timeout_seconds: float) -> Peer:
            assert port == 47474
            assert timeout_seconds == pytest.approx(0.2)
            if address != "192.168.1.12":
                raise OSError("not a peer")
            return Peer(
                device_id="a" * 32,
                name="Desktop",
                address=address,
                port=port,
                fingerprint="b" * 64,
                platform="windows",
            )

    discovered: list[Peer] = []
    progress: list[tuple[int, int]] = []
    peers = await scan_lan(
        FakeClient(),  # type: ignore[arg-type]
        47474,
        targets=["192.168.1.11", "192.168.1.12", "192.168.1.13"],
        timeout_seconds=0.2,
        peer_callback=discovered.append,
        progress_callback=lambda done, total: progress.append((done, total)),
    )

    assert [peer.name for peer in peers] == ["Desktop"]
    assert [peer.address for peer in discovered] == ["192.168.1.12"]
    assert progress[-1] == (3, 3)
