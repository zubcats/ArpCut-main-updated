"""Victim prep and stack warm-up for impairment (extracted from MainWindow)."""
from __future__ import annotations

import sys
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication

from tools.clumsy_inline import (
    apply_clumsy_ics_router_context,
    clumsy_ics_downstream_prefix,
    clumsy_ics_lag_can_use_windivert,
    clumsy_mode_enabled,
)
from gui.impairment_shared import UI_LOG_RESTORE_FG, UI_LOG_VICTIM_BLOCK_FG


class ImpairmentPrepMixin:
    def _ics_stack_is_warm(self) -> bool:
        """True when ICS iface/router prep ran recently (startup or wake-from-sleep)."""
        warmed_at = float(getattr(self, '_impairment_stack_warmed_at', 0.0))
        if warmed_at <= 0.0 or time.monotonic() - warmed_at > 300.0:
            return False
        if not clumsy_mode_enabled() or not sys.platform.startswith('win'):
            return False
        try:
            from tools.clumsy_ics import read_clumsy_ics_state

            want = str(read_clumsy_ics_state().get('downstream_name') or '').strip()
            if not want:
                return False
            cur = str(getattr(self.scanner.iface, 'name', None) or '').strip()
            return cur == want
        except Exception:
            return False


    def _schedule_impairment_stack_warm(self, reason: str = 'startup') -> None:
        """Defer ICS/WinDivert prep so Kill/Lag/Dupe clicks skip slow checks."""
        if getattr(self, '_shutting_down', False):
            return
        delay = 0 if reason in ('post_scan', 'reactivate', 'select', 'post_init', 'settings') else 80
        QTimer.singleShot(delay, lambda r=reason: self._warm_impairment_stack(reason=r))


    def _warm_impairment_stack(self, *, reason: str = 'startup') -> None:
        """
        Bind hotspot NIC + home-LAN router context once per session (or after sleep).
        Lag/Dupe/Kill toggles reuse this instead of re-running netsh/ARP on every click.
        """
        _ = reason
        if getattr(self, '_impairment_warm_in_flight', False):
            return
        if getattr(self, '_shutting_down', False):
            return
        self._impairment_warm_in_flight = True
        try:
            self._warm_lan_mitm_stack()
            if not sys.platform.startswith('win') or not clumsy_mode_enabled():
                return
            from tools.clumsy_inline import (
                clumsy_ics_downstream_ifidx,
                clumsy_ics_upstream_ifidx,
                sync_scanner_iface_for_ics_downstream,
            )

            sync_scanner_iface_for_ics_downstream(self.scanner)
            prefix = clumsy_ics_downstream_prefix()
            gw = prefix.rstrip('.') + '.1'
            apply_clumsy_ics_router_context(self.scanner, self.killer, gw)
            self.killer.iface = self.scanner.iface
            clumsy_ics_downstream_ifidx()
            clumsy_ics_upstream_ifidx()
            probe = self._get_selected_device()
            self._windivert_ready_cached = clumsy_ics_lag_can_use_windivert(
                probe if isinstance(probe, dict) else {}, self.scanner
            )
            self._impairment_stack_warmed_at = time.monotonic()
        except Exception:
            pass
        finally:
            self._impairment_warm_in_flight = False


    def _start_impairment_warm_on_reactivate(self) -> None:
        """Re-warm ICS stack when the app returns from sleep / long background."""
        if not sys.platform.startswith('win'):
            return
        app = QApplication.instance()
        if app is None or getattr(self, '_impairment_warm_state_hooked', False):
            return
        self._impairment_warm_state_hooked = True
        app.applicationStateChanged.connect(self._on_app_state_for_impairment_warm)


    def _on_app_state_for_impairment_warm(self, state) -> None:
        if state in (Qt.ApplicationInactive, Qt.ApplicationHidden):
            self._last_app_inactive_mono = time.monotonic()
            return
        if state != Qt.ApplicationActive:
            return
        inactive_for = time.monotonic() - float(getattr(self, '_last_app_inactive_mono', 0.0))
        if inactive_for >= 45.0:
            self._schedule_impairment_stack_warm('reactivate')


    def _migrate_killed_profile_for_device_change(
        self, old_mac: str, old_ip: str, device: dict
    ) -> None:
        """Move Kill ON / pending state when resolve_live_lan_victim updates MAC or IP."""
        if not isinstance(device, dict):
            return
        try:
            from networking.nicknames import nickname_profile_key

            old_pk = nickname_profile_key(old_mac, old_ip) if old_mac and old_ip else ''
        except Exception:
            old_pk = ''
        if not old_pk:
            old_pk = str(old_mac or '').strip()
        new_pk = self._killed_profile_key(device)
        if not old_pk or not new_pk or old_pk == new_pk:
            return
        was_on = bool(self.killed_devices.pop(old_pk, False))
        pending = getattr(self, '_kill_pending_profiles', set())
        was_pending = old_pk in pending
        if was_on:
            self.killed_devices[new_pk] = True
        if was_pending:
            pending.discard(old_pk)
            pending.add(new_pk)
            self._kill_pending_profiles = pending


    def _rekey_kill_bookkeeping(self, old_mac: str, device: dict) -> str:
        """Keep intent/snapshot keys aligned when ARP refresh updates the victim MAC."""
        new_mac = str((device or {}).get('mac') or '').strip()
        if not new_mac or new_mac == old_mac:
            return old_mac or new_mac
        seq = self._kill_intent_seq.pop(old_mac, None)
        if seq is not None:
            self._kill_intent_seq[new_mac] = seq
        snap_map = getattr(self, '_kill_device_snapshot', None)
        if isinstance(snap_map, dict) and old_mac in snap_map:
            snap_map[new_mac] = dict(device)
            snap_map.pop(old_mac, None)
        return new_mac


    def _refresh_victim_mac_from_system_arp(self, device) -> None:
        """Use the OS ARP cache (ping once if missing) so poison targets the live PS5 MAC."""
        if not isinstance(device, dict):
            return
        try:
            from tools.utils import (
                lookup_mac_from_arp_table,
                mac_address_is_usable,
                run_command,
            )

            ip = str(device.get('ip') or '').strip()
            if not ip:
                return
            iface_ip = str(getattr(self.scanner.iface, 'ip', None) or '').strip()
            mac = lookup_mac_from_arp_table(ip, iface_ip)
            if not mac_address_is_usable(mac) and sys.platform.startswith('win'):
                try:
                    run_command(
                        ['ping', '-n', '1', '-w', '400', ip],
                        shell=False,
                        timeout=2,
                    )
                except Exception:
                    pass
                mac = lookup_mac_from_arp_table(ip, iface_ip)
            if mac_address_is_usable(mac):
                old_mac = str(device.get('mac') or '').strip()
                from tools.utils import _resolve_allowed_macs, good_mac

                got = good_mac(mac)
                if not mac_address_is_usable(old_mac):
                    device['mac'] = got
                elif got != good_mac(old_mac):
                    # PS5 Ethernet ↔ Wi‑Fi uses different MACs; allow handoff when
                    # nickname-linked or the row IP's ARP MAC is authoritative.
                    allowed = _resolve_allowed_macs(device)
                    if got not in allowed:
                        return
                device['mac'] = got
                if old_mac and old_mac != mac and old_mac in self.killer.killed:
                    entry = dict(self.killer.killed.pop(old_mac))
                    entry['mac'] = mac
                    self.killer.killed[mac] = entry
                elif mac in self.killer.killed:
                    self.killer.killed[mac] = dict(device)
        except Exception:
            pass


    def _prepare_ics_victim_context(self, device) -> dict:
        """
        Bind the ICS downstream NIC (Mobile Hotspot / console Ethernet) and resolve
        the live 192.168.137.x (or ICS) IP before WinDivert or ICS-ARP impairment.
        """
        dev = self._device_with_plan_ip(dict(device) if isinstance(device, dict) else {})
        if not isinstance(dev, dict):
            return {}
        from tools.clumsy_inline import (
            apply_clumsy_ics_router_context,
            clumsy_ics_resolve_victim_ip,
            sync_scanner_iface_for_ics_downstream,
        )

        warm = self._ics_stack_is_warm()
        if not warm:
            try:
                sync_scanner_iface_for_ics_downstream(self.scanner)
            except Exception:
                pass
        plan = self._impairment_plan_for(dev)
        rip = (
            clumsy_ics_resolve_victim_ip(dev, self.scanner)
            or plan.resolved_ip
            or str(dev.get('ip') or '').strip()
        )
        if rip:
            dev['ip'] = rip
        if not warm:
            try:
                apply_clumsy_ics_router_context(self.scanner, self.killer, dev.get('ip'))
            except Exception:
                pass
        self.killer.iface = self.scanner.iface
        self.killer.router = getattr(self.scanner, 'router', None) or self.killer.router
        return dev


    def _prepare_victim_for_impairment(self, device, *, fast: bool = True) -> dict:
        """
        Unified prep before Kill/Lag/Dupe/Cut/Advanced: hotspot binds the ICS
        downstream NIC and resolves the live client IP; home LAN resolves the victim
        on the correct adapter.
        """
        dev = dict(device) if isinstance(device, dict) else {}
        if not dev.get('ip'):
            return dev
        plan = self._impairment_plan_for(dev)
        if clumsy_mode_enabled() and plan.is_ics_downstream:
            prepared = self._prepare_ics_victim_context(dev)
            return prepared if isinstance(prepared, dict) and prepared else dev
        self._ensure_network_context_for_victim(dev, fast=fast)
        return dev


    def _ensure_network_context_for_victim(self, device, *, fast: bool = True) -> bool:
        """
        Bind scanner + killer to the NIC that routes to the victim (e.g. hotspot vs Ethernet).
        Runtime only — does not write ``iface`` to settings (so Clumsy/victim auto-pick
        does not replace your chosen adapter in zubcut.json).

        Applies the network stack prep that Clumsy enable/repair + restart used to do
        implicitly (ARP flush, topology refresh, Windows IP forwarding).
        """
        if not device or not device.get('ip'):
            return False
        plan = self._impairment_plan_for(device)
        if clumsy_mode_enabled() and plan.is_ics_downstream:
            try:
                prepared = self._prepare_victim_for_impairment(device, fast=fast)
                if isinstance(prepared, dict) and prepared:
                    old_ip = str(device.get('ip') or '').strip()
                    device.clear()
                    device.update(prepared)
                    new_ip = str(device.get('ip') or '').strip()
                    if new_ip and new_ip != old_ip:
                        self.log(
                            f'Hotspot target resolved to {new_ip} for impairment.',
                            UI_LOG_VICTIM_BLOCK_FG,
                        )
            except Exception:
                pass
            return True
        if fast and self._lan_mitm_stack_is_warm():
            self.killer.iface = self.scanner.iface
            self.killer.router = getattr(self.scanner, 'router', None) or self.killer.router
            return True
        try:
            from tools.utils import resolve_live_lan_victim

            iface_ip = str(getattr(self.scanner.iface, 'ip', None) or '').strip()
            resolved, hint = resolve_live_lan_victim(
                device,
                getattr(self.scanner, 'devices', None) or [],
                iface_ip,
                ping_attempts=1 if fast else 3,
            )
            if isinstance(resolved, dict):
                old_ip = str(device.get('ip') or '').strip()
                old_mac = str(device.get('mac') or '').strip()
                device.clear()
                device.update(resolved)
                new_ip = str(device.get('ip') or '').strip()
                new_mac = str(device.get('mac') or '').strip()
                if hint:
                    self.log(hint, 'red' if 'Rescan' in hint else UI_LOG_VICTIM_BLOCK_FG)
                elif new_ip != old_ip or new_mac != old_mac:
                    self.log(
                        f'Target updated to {new_ip} ({new_mac}) for MITM.',
                        UI_LOG_VICTIM_BLOCK_FG,
                    )
                if new_mac and new_mac != old_mac:
                    self._rekey_kill_bookkeeping(old_mac, device)
                if new_ip != old_ip or new_mac != old_mac:
                    self._migrate_killed_profile_for_device_change(
                        old_mac, old_ip, device
                    )
        except Exception:
            pass
        changed = False
        try:
            changed = bool(self.scanner.sync_iface_for_victim_ip(device['ip']))
        except Exception:
            pass
        # Only refresh router/local topology when we actually changed iface OR the
        # scanner doesn't have a valid router_mac yet. The previous unconditional
        # refresh ran get_gateway_mac, which falls back to scapy.getmacbyip() with a
        # ~4 s ARP timeout when the system ARP cache is empty — and we ourselves
        # wipe that cache with flush_arp on every kill, guaranteeing the next Kill
        # ON pays the full 4 s timeout. Skip both when the cache is still good.
        try:
            from tools.utils import lookup_mac_from_arp_table, mac_address_is_usable

            self._refresh_victim_mac_from_system_arp(device)
            self._refresh_router_mac_from_system_arp()
            router_mac = getattr(self.scanner, 'router_mac', '') or ''
            need_topo = changed or not mac_address_is_usable(router_mac)
            if need_topo and not fast:
                self.scanner.refresh_local_topology()
                self._refresh_router_mac_from_system_arp()
            elif need_topo and fast and not mac_address_is_usable(router_mac):
                # Fast arm: one ping already ran in _refresh_router_mac_from_system_arp.
                # Avoid refresh_local_topology → scapy getmacbyip (~4s) on the GUI thread.
                pass
        except Exception:
            pass
        if clumsy_mode_enabled():
            try:
                apply_clumsy_ics_router_context(self.scanner, self.killer, device['ip'])
            except Exception:
                pass
        # Only invalidate the cached L2 socket if the iface actually changed. The
        # unconditional close here was a major Kill ON delay: Npcap/conf.L2socket()
        # reopen on Windows costs ~0.5–2 s, which fires inside the ARP worker on the
        # very first _send_packet after every Kill ON. Kill OFF was instant because it
        # never reaches this function and the socket stays warm.
        prev_iface_guid = getattr(getattr(self.killer, 'iface', None), 'guid', None)
        new_iface_guid = getattr(self.scanner.iface, 'guid', None)
        self.killer.iface = self.scanner.iface
        self.killer.router = self.scanner.router
        if prev_iface_guid != new_iface_guid:
            self.killer._close_socket()
        try:
            from scapy.all import conf as scapy_conf

            guid = self.scanner.iface.guid if self.scanner.iface else None
            if guid:
                scapy_conf.iface = guid
        except Exception:
            pass
        if changed:
            label = (getattr(self.scanner.iface, 'name', None) or '').strip() or getattr(
                self.scanner.iface, 'guid', ''
            )
            self.log(
                f'Using network adapter for {device["ip"]}: {label}',
                UI_LOG_RESTORE_FG,
            )
        return True


    def _clear_stale_ics_mitm(self, device) -> None:
        """Drop ARP MITM left on a hotspot client from an older build or non-ICS path."""
        if device['mac'] not in self.killer.killed:
            return
        try:
            victim = self._victim_record_for_mac(device['mac']) or device
            self.killer.unkill(victim)
        except Exception:
            pass
