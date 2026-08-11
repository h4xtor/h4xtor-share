from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Callable, Iterable

from h4xtor_share.client import PeerClient
from h4xtor_share.discovery import local_ipv4_addresses
from h4xtor_share.models import Peer

DEFAULT_PREFIX = 24
MAX_SCAN_HOSTS = 1024


def scan_targets(
    addresses: Iterable[str],
    *,
    prefix: int = DEFAULT_PREFIX,
    max_hosts: int = MAX_SCAN_HOSTS,
) -> list[str]:
    """Return unique IPv4 hosts for the local networks containing *addresses*.

    The local interface addresses themselves are excluded. The host limit prevents
    an accidental scan of an enormous network when the user supplies a broad CIDR.
    """

    local: set[ipaddress.IPv4Address] = set()
    networks: set[ipaddress.IPv4Network] = set()
    for raw in addresses:
        parsed = ipaddress.ip_address(raw)
        if not isinstance(parsed, ipaddress.IPv4Address):
            continue
        local.add(parsed)
        networks.add(ipaddress.ip_network(f"{parsed}/{prefix}", strict=False))

    hosts: list[str] = []
    seen: set[ipaddress.IPv4Address] = set()
    for network in sorted(networks, key=lambda item: (int(item.network_address), item.prefixlen)):
        for host in network.hosts():
            if host in local or host in seen:
                continue
            seen.add(host)
            hosts.append(str(host))
            if len(hosts) > max_hosts:
                raise ValueError(
                    f"LAN scan is limited to {max_hosts} hosts. Use a narrower range."
                )
    return hosts


def cidr_targets(cidr: str, *, max_hosts: int = MAX_SCAN_HOSTS) -> list[str]:
    network = ipaddress.ip_network(cidr.strip(), strict=False)
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Only IPv4 LAN ranges are supported.")
    count = max(0, int(network.num_addresses) - (2 if network.prefixlen <= 30 else 0))
    if count > max_hosts:
        raise ValueError(
            f"LAN scan is limited to {max_hosts} hosts. Use a narrower range."
        )
    return [str(host) for host in network.hosts()]


async def scan_lan(
    client: PeerClient,
    port: int,
    *,
    targets: Iterable[str] | None = None,
    timeout_seconds: float = 0.75,
    concurrency: int = 64,
    peer_callback: Callable[[Peer], None] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[Peer]:
    """Probe hosts concurrently for a compatible h4xtor-share endpoint."""

    candidates = list(targets) if targets is not None else scan_targets(local_ipv4_addresses())
    if not candidates:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))
    peers: dict[str, Peer] = {}
    completed = 0
    completed_lock = asyncio.Lock()

    async def probe(address: str) -> None:
        nonlocal completed
        try:
            async with semaphore:
                peer = await client.get_info(
                    address,
                    port,
                    timeout_seconds=timeout_seconds,
                )
        except (TimeoutError, OSError, ValueError, RuntimeError):
            peer = None
        except Exception:
            # aiohttp exposes several transport-specific exception subclasses.
            # A failed probe is expected during a LAN scan and must not abort it.
            peer = None

        if peer is not None:
            peers[peer.device_id] = peer
            if peer_callback:
                peer_callback(peer)

        async with completed_lock:
            completed += 1
            if progress_callback:
                progress_callback(completed, len(candidates))

    await asyncio.gather(*(probe(address) for address in candidates))
    return sorted(peers.values(), key=lambda peer: (peer.name.casefold(), peer.address))
