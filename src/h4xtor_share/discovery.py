from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable

import ifaddr
from zeroconf import ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

from h4xtor_share.config import Config
from h4xtor_share.models import DESKTOP_CAPABILITIES, Peer

SERVICE_TYPE = "_h4xtor-share._tcp.local."


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            value = ip.ip[0] if isinstance(ip.ip, tuple) else ip.ip
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                continue
            if parsed.version == 4 and not parsed.is_loopback and not parsed.is_link_local:
                addresses.add(str(parsed))
    return sorted(addresses)


def local_broadcast_addresses() -> list[str]:
    """Directed broadcast address of every active IPv4 interface (e.g. 192.168.1.255)."""
    targets: set[str] = set()
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            value = ip.ip[0] if isinstance(ip.ip, tuple) else ip.ip
            try:
                interface = ipaddress.ip_interface(f"{value}/{ip.network_prefix}")
            except ValueError:
                continue
            if interface.version != 4 or interface.ip.is_loopback or interface.ip.is_link_local:
                continue
            if interface.network.prefixlen >= 31:
                continue
            targets.add(str(interface.network.broadcast_address))
    return sorted(targets)


def property_text(properties: dict[bytes, bytes], key: str, default: str = "") -> str:
    value = properties.get(key.encode("utf-8"))
    return value.decode("utf-8", errors="replace") if value else default


class DiscoveryService:
    def __init__(
        self,
        config: Config,
        fingerprint: str,
        peer_callback: Callable[[Peer], None],
    ) -> None:
        self.config = config
        self.fingerprint = fingerprint
        self.peer_callback = peer_callback
        self.zeroconf = Zeroconf()
        self.service_info: ServiceInfo | None = None
        self.browser: ServiceBrowser | None = None

    def start(self) -> None:
        addresses = local_ipv4_addresses()
        if not addresses:
            raise RuntimeError("No active IPv4 network interface was found.")
        packed_addresses = [socket.inet_aton(address) for address in addresses]
        service_name = f"{self.config.device_id}.{SERVICE_TYPE}"
        self.service_info = ServiceInfo(
            SERVICE_TYPE,
            service_name,
            addresses=packed_addresses,
            port=self.config.port,
            properties={
                "id": self.config.device_id,
                "name": self.config.device_name,
                "fingerprint": self.fingerprint,
                "platform": self.config.platform_name,
                "protocol": "1",
                "capabilities": ",".join(DESKTOP_CAPABILITIES),
            },
            server=f"{self.config.device_id}.local.",
        )
        self.zeroconf.register_service(self.service_info, allow_name_change=False)
        self.browser = ServiceBrowser(
            self.zeroconf,
            SERVICE_TYPE,
            handlers=[self._service_changed],
        )

    def stop(self) -> None:
        if self.browser:
            self.browser.cancel()
        if self.service_info:
            self.zeroconf.unregister_service(self.service_info)
        self.zeroconf.close()
        self.browser = None
        self.service_info = None

    def _service_changed(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change not in {
            ServiceStateChange.Added,
            ServiceStateChange.Updated,
        }:
            return
        info = zeroconf.get_service_info(service_type, name, timeout=2000)
        if not info:
            return
        device_id = property_text(info.properties, "id")
        if not device_id or device_id == self.config.device_id:
            return
        addresses = info.parsed_scoped_addresses()
        ipv4 = next(
            (
                address
                for address in addresses
                if ":" not in address and not address.startswith("127.")
            ),
            None,
        )
        if not ipv4:
            return
        raw_capabilities = property_text(info.properties, "capabilities")
        capabilities = tuple(
            capability.strip()
            for capability in raw_capabilities.split(",")
            if capability.strip()
        )
        self.peer_callback(
            Peer(
                device_id=device_id,
                name=property_text(info.properties, "name", name),
                address=ipv4,
                port=info.port,
                fingerprint=property_text(info.properties, "fingerprint"),
                platform=property_text(info.properties, "platform", "unknown"),
                transport="lan",
                capabilities=capabilities,
            )
        )
