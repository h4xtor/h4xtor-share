"""The "Wi-Fi + 5G" page: combine this PC's internet with paired phones' mobile data.

Mixed into ``H4xtorShareApp`` like the phone pages. The proxy itself lives in
``netmerge.py``; the system proxy switch in ``sysproxy.py``.
"""

from __future__ import annotations

import asyncio
import tkinter as tk
from typing import Any

from h4xtor_share import sysproxy
from h4xtor_share.netmerge import NETMERGE_PORT_OFFSET, Link, NetMerge
from h4xtor_share.ui_kit import Card, ScrollFrame

PHONE_POLL_MS = 15_000
TICK_MS = 1_500


def _rate(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} MB/s".replace(".", ",")
    return f"{value / 1000:.0f} kB/s"


def _amount(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} GB".replace(".", ",")
    return f"{value / 1_000_000:.1f} MB".replace(".", ",")


def link_detail(link: Link) -> str:
    if link.kind == "phone":
        base = f"Telefon · {(link.phone.network if link.phone else '') or 'mobildata'}"
    else:
        base = f"Denne PC · {link.bind}"
    if not link.healthy:
        return base + " · intet internet"
    latency = f" · {link.latency * 1000:.0f} ms" if link.latency is not None else ""
    return base + latency


class NetMergePageMixin:
    # Relies on H4xtorShareApp attributes (theme, config_store, runtime, client, peers ...).
    def _init_netmerge(self) -> None:
        self.netmerge = NetMerge(self.config_store.port + NETMERGE_PORT_OFFSET)
        self.netmerge_rows: dict[str, dict[str, tk.Label]] = {}
        self.netmerge_error = ""

    @property
    def netmerge_enabled(self) -> bool:
        return bool(self.config_store.data.get("netmerge_enabled", False))

    # ---------------------------------------------------------------------- page
    def _build_netmerge_page(self) -> None:
        c = self.theme.c
        px = self.theme.px
        page, _actions = self._page(
            "netmerge",
            "Wi-Fi + 5G",
            "Brug Wi-Fi og telefoners mobildata på én gang – mere fart, når I er flere.",
        )
        scroll = ScrollFrame(page, self.theme)
        scroll.pack(fill="both", expand=True, padx=(px(36), px(24)), pady=(0, px(16)))
        inner = scroll.inner

        hero = Card(inner, self.theme)
        hero.pack(fill="x", pady=(0, px(14)))
        self.netmerge_toggle = self._toggle_row(
            hero.body,
            "Kombinér forbindelser",
            "Nye forbindelser fordeles på alle links med internet. Hurtige links får flest.",
            self.netmerge_enabled,
            self.set_netmerge_enabled,
        )
        self._divider(hero.body)
        self.netmerge_status = tk.Label(
            hero.body,
            text="",
            bg=c["card"],
            fg=c["text"],
            font=self.theme.title_font(15),
            anchor="w",
        )
        self.netmerge_status.pack(fill="x")
        self.netmerge_substatus = tk.Label(
            hero.body,
            text="",
            bg=c["card"],
            fg=c["muted"],
            font=self.theme.font(9),
            anchor="w",
            justify="left",
            wraplength=px(640),
        )
        self.netmerge_substatus.pack(fill="x", pady=(px(2), 0))

        links = Card(inner, self.theme)
        links.pack(fill="x", pady=(0, px(14)))
        tk.Label(
            links.body,
            text="Forbindelser",
            bg=c["card"],
            fg=c["text"],
            font=self.theme.font(11, "bold"),
            anchor="w",
        ).pack(fill="x")
        self.netmerge_list = tk.Frame(links.body, bg=c["card"])
        self.netmerge_list.pack(fill="x", pady=(px(8), 0))

        guide = Card(inner, self.theme)
        guide.pack(fill="x", pady=(0, px(14)))
        tk.Label(
            guide.body,
            text="Få 5G med fra en ven",
            bg=c["card"],
            fg=c["text"],
            font=self.theme.font(11, "bold"),
            anchor="w",
        ).pack(fill="x")
        for number, text in (
            ("1", "Vennen installerer h4xtor share på sin Android og går på samme Wi-Fi"),
            ("2", "Tryk “Forbind ny enhed” her og scan QR-koden med telefonen"),
            ("3", "På telefonen: slå “Del mobildata med PC'en” til – den dukker op her"),
        ):
            row = tk.Frame(guide.body, bg=c["card"])
            row.pack(fill="x", pady=px(4))
            tk.Label(
                row,
                text=number,
                width=2,
                bg=c["accent_soft"],
                fg=c["accent"],
                font=self.theme.font(10, "bold"),
            ).pack(side="left")
            tk.Label(
                row,
                text=text,
                bg=c["card"],
                fg=c["text"],
                font=self.theme.font(10),
                anchor="w",
            ).pack(side="left", padx=(px(10), 0))
        tk.Label(
            guide.body,
            text="Godt at vide: én forbindelse bruger altid ét link, så en enkelt stor download "
            "bliver ikke hurtigere – websider, apps, opdateringer og downloads med flere "
            "forbindelser gør. Telefoner bruger deres mobildata, mens det er slået til. "
            "Har PC'en selv to netkort (fx Wi-Fi + USB-deling fra en telefon), bruges begge. "
            f"Andre programmer kan bruge proxy 127.0.0.1:{self.netmerge.port} (HTTP eller SOCKS5).",
            bg=c["card"],
            fg=c["faint"],
            font=self.theme.font(8),
            anchor="w",
            justify="left",
            wraplength=px(640),
        ).pack(fill="x", pady=(px(12), 0))
        self._refresh_netmerge()
        self.after(TICK_MS, self._netmerge_tick)
        self.after(3_000, self._netmerge_poll_phones)

    def _refresh_netmerge(self) -> None:
        c = self.theme.c
        px = self.theme.px
        links = sorted(
            self.netmerge.links.values(), key=lambda link: (not link.healthy, link.kind, link.name)
        )
        if not self.netmerge.running:
            self.netmerge_status.configure(text="Slået fra")
            self.netmerge_substatus.configure(
                text=self.netmerge_error
                or "Slå til for at bruge alle forbindelser – også din vens 5G."
            )
        else:
            healthy = [link for link in links if link.healthy]
            total = sum(link.speed() for link in links)
            self.netmerge_status.configure(
                text=f"Kører · {len(healthy)} {'link' if len(healthy) == 1 else 'links'} "
                f"med internet · {_rate(total)} lige nu"
            )
            self.netmerge_substatus.configure(
                text=self.netmerge_error
                or (
                    "Kun ét link lige nu – par en vens telefon for at få mere fart."
                    if len(healthy) < 2
                    else "Nye forbindelser fordeles automatisk."
                )
            )
        received = sum(link.received for link in links) or 1
        for key in [key for key in self.netmerge_rows if key not in self.netmerge.links]:
            self.netmerge_rows.pop(key)["frame"].destroy()
        if not links:
            if not self.netmerge_rows:
                self.netmerge_rows["_empty"] = {
                    "frame": tk.Label(
                        self.netmerge_list,
                        text="Ingen forbindelser fundet endnu.",
                        bg=c["card"],
                        fg=c["faint"],
                        font=self.theme.font(9),
                        anchor="w",
                    )
                }
                self.netmerge_rows["_empty"]["frame"].pack(fill="x")
            return
        for link in links:
            row = self.netmerge_rows.get(link.key)
            if row is None:
                frame = tk.Frame(self.netmerge_list, bg=c["card"])
                frame.pack(fill="x", pady=px(4))
                row = {"frame": frame}
                row["dot"] = tk.Label(frame, text="●", bg=c["card"], font=self.theme.font(9))
                row["dot"].pack(side="left")
                texts = tk.Frame(frame, bg=c["card"])
                texts.pack(side="left", fill="x", expand=True, padx=(px(8), 0))
                row["name"] = tk.Label(
                    texts,
                    bg=c["card"],
                    fg=c["text"],
                    font=self.theme.font(10, "bold"),
                    anchor="w",
                )
                row["name"].pack(fill="x")
                row["detail"] = tk.Label(
                    texts, bg=c["card"], fg=c["muted"], font=self.theme.font(8), anchor="w"
                )
                row["detail"].pack(fill="x")
                row["numbers"] = tk.Label(
                    frame,
                    bg=c["card"],
                    fg=c["text"],
                    font=self.theme.font(9),
                    anchor="e",
                    justify="right",
                )
                row["numbers"].pack(side="right")
                self.netmerge_rows[link.key] = row
            row["dot"].configure(fg=c["success"] if link.healthy else c["faint"])
            row["name"].configure(text=link.name)
            row["detail"].configure(text=link_detail(link))
            row["numbers"].configure(
                text=f"{_rate(link.speed())}\n{link.received * 100 // received} % · "
                f"{_amount(link.received + link.sent)}"
            )
        empty = self.netmerge_rows.pop("_empty", None)
        if empty is not None:
            empty["frame"].destroy()

    def _netmerge_tick(self) -> None:
        if getattr(self, "_closing", False):
            return
        if getattr(self, "active_page", "") == "netmerge":
            self._refresh_netmerge()
        self.after(TICK_MS, self._netmerge_tick)

    # ------------------------------------------------------------------- on/off
    def set_netmerge_enabled(self, value: bool) -> None:
        self.config_store.data["netmerge_enabled"] = value
        self.config_store.save()
        self.netmerge_error = ""
        self._phone_call(
            self._netmerge_start() if value else self._netmerge_stop(), self._netmerge_switched
        )

    def _netmerge_switched(self, ok: bool, result: Any) -> None:
        if not ok:
            self.netmerge_error = str(result)
            if isinstance(result, OSError) and not self.netmerge.running:
                self.config_store.data["netmerge_enabled"] = False
                self.netmerge_error = (
                    f"Kunne ikke starte: port {self.netmerge.port} er optaget ({result})."
                )
                self.toast.show(self.netmerge_error, "danger", 6000)
        elif isinstance(result, dict):
            # An older saved state only survives a crash; it holds the user's real settings.
            self.config_store.data.setdefault("netmerge_proxy_saved", result)
        elif result == "restored":
            self.config_store.data.pop("netmerge_proxy_saved", None)
        if isinstance(result, str) and result.startswith("manual:"):
            self.netmerge_error = (
                "Systemets proxy kunne ikke sættes automatisk. Sæt den selv til "
                f"127.0.0.1:{self.netmerge.port}  ({result[7:]})"
            )
        self.config_store.save()
        self.netmerge_toggle.set(self.netmerge_enabled and self.netmerge.running)
        self._refresh_netmerge()
        if ok and self.netmerge.running:
            self._netmerge_poll_phones(reschedule=False)

    async def _netmerge_start(self) -> dict[str, Any] | str:
        await self.netmerge.start()
        try:
            return await asyncio.to_thread(sysproxy.apply, self.netmerge.pac_url)
        except Exception as error:  # noqa: BLE001 - the proxy still works when set by hand
            return f"manual:{error}"

    async def _netmerge_stop(self) -> str:
        saved = self.config_store.data.get("netmerge_proxy_saved")
        await self.netmerge.stop()
        if isinstance(saved, dict):
            await asyncio.to_thread(sysproxy.restore, saved, self.netmerge.pac_url)
        return "restored"

    async def _netmerge_resume(self) -> None:
        """At start-up: switch back on, or undo a system proxy left by a crash."""
        if self.netmerge_enabled:
            result = await self._netmerge_start()
            self.event_queue.put(("phone_call", (self._netmerge_switched, True, result)))
        elif isinstance(self.config_store.data.get("netmerge_proxy_saved"), dict):
            result = await self._netmerge_stop()
            self.event_queue.put(("phone_call", (self._netmerge_switched, True, result)))

    async def _netmerge_shutdown(self) -> None:
        """App closing: put the system proxy back but remember that it was on."""
        if self.netmerge.running:
            await self._netmerge_stop()
            # The Tk thread is blocked in close(), so saving from here cannot race it.
            self.config_store.data.pop("netmerge_proxy_saved", None)
            self.config_store.save()

    # ------------------------------------------------------------------ phones
    def _netmerge_poll_phones(self, reschedule: bool = True) -> None:
        if getattr(self, "_closing", False):
            return
        if self.netmerge.running:
            phones = [
                peer
                for peer in self._trusted_peers()
                if peer.supports("net-gateway")
                and getattr(self.peer_status.get(peer.device_id), "online", True)
            ]
            self.runtime.submit(self._netmerge_update_phones(phones), "netmerge_phones")
        if reschedule:
            self.after(PHONE_POLL_MS, self._netmerge_poll_phones)

    async def _netmerge_update_phones(self, phones: list[Any]) -> None:
        sharing: set[str] = set()

        async def check(peer: Any) -> None:
            try:
                status = await self.client.net_share_status(peer)
            except Exception:  # noqa: BLE001 - offline or old phone: just not a link
                return
            if not status.get("enabled"):
                return
            route = self.client.net_route(peer)
            route.network = str(status.get("network") or "")
            sharing.add(peer.device_id)
            known = self.netmerge.links.get(f"phone:{peer.device_id}")
            self.netmerge.set_phone(peer.device_id, peer.name, route)
            if known is None or not known.healthy:
                await self.netmerge.probe(self.netmerge.links[f"phone:{peer.device_id}"])

        await asyncio.gather(*(check(peer) for peer in phones))
        for device_id in list(self.netmerge.phone_routes):
            if device_id not in sharing:
                self.netmerge.set_phone(device_id, "", None)
