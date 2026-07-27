from __future__ import annotations

import importlib.util
import platform
from dataclasses import dataclass

from h4xtor_share.discovery import local_ipv4_addresses


@dataclass(frozen=True, slots=True)
class TransportStatus:
    name: str
    available: bool
    data_path_ready: bool
    detail: str


def detect_transports() -> list[TransportStatus]:
    system = platform.system().lower()
    addresses = local_ipv4_addresses()
    network_detail = (
        f"Active interfaces: {', '.join(addresses)}"
        if addresses
        else "No active IPv4 interface"
    )
    bluetooth_library = importlib.util.find_spec("bleak") is not None

    if system == "windows":
        wifi_direct_detail = (
            "Transfers work over an existing Windows Wi-Fi Direct or Mobile Hotspot link. "
            "Group provisioning remains OS-managed."
        )
    elif system == "linux":
        wifi_direct_detail = (
            "Transfers work over an existing NetworkManager/wpa_supplicant P2P link. "
            "Group provisioning remains OS-managed."
        )
    elif system == "darwin":
        wifi_direct_detail = (
            "Transfers work over a shared local or hotspot link. macOS does not expose a "
            "general-purpose public Wi-Fi Direct provisioning API."
        )
    else:
        wifi_direct_detail = "Transfers work over any existing IP-capable peer-to-peer link."

    return [
        TransportStatus(
            name="LAN / Wi-Fi",
            available=bool(addresses),
            data_path_ready=bool(addresses),
            detail=network_detail,
        ),
        TransportStatus(
            name="Wi-Fi Direct",
            available=bool(addresses),
            data_path_ready=bool(addresses),
            detail=wifi_direct_detail,
        ),
        TransportStatus(
            name="Bluetooth",
            available=bluetooth_library,
            data_path_ready=False,
            detail=(
                "BLE discovery library is installed, but cross-platform bulk transfer requires "
                "native peripheral adapters for Windows, macOS and BlueZ."
                if bluetooth_library
                else "Install the bluetooth extra for BLE discovery. Native bulk-transfer "
                "adapters are not enabled in this release."
            ),
        ),
    ]
