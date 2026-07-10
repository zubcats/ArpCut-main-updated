"""Victim/plan helpers for impairment flows (extracted from MainWindow)."""
from __future__ import annotations

from networking.nicknames import parse_nickname_profile_key
from tools.clumsy_inline import clumsy_ics_resolve_victim_ip, clumsy_mode_enabled
from tools.ics_impairment_policy import (
    classify_device_impairment,
    device_row_for_impairment,
    impairment_status_line,
    should_restore_remembered_kill,
)
from tools.pfctl import _is_valid_ip
from tools.utils_gui import set_settings
from gui.impairment_shared import UI_LOG_RESTORE_FG, UI_LOG_VICTIM_BLOCK_FG


class ImpairmentPlanMixin:
    def _impairment_plan_for(self, device):
        """Classify how Kill/Lag/Dupe/Cut/Advanced should affect this device (fresh each call)."""
        return classify_device_impairment(device, self.scanner)


    def _uses_windivert(self, device) -> bool:
        return self._impairment_plan_for(device).use_windivert


    def _is_ics_downstream(self, device) -> bool:
        return self._impairment_plan_for(device).is_ics_downstream


    def _victim_row(self, device, plan=None, *, lag=False, dupe=False, pctcut=False, mitmshape=False):
        """Resolved device row + plan (single entry point for victim IP)."""
        plan = plan or self._impairment_plan_for(device)
        row = device_row_for_impairment(device, self.scanner, plan)
        ip = self._flow_stable_victim_ip(
            row, lag=lag, dupe=dupe, pctcut=pctcut, mitmshape=mitmshape
        )
        if ip:
            row = dict(row)
            row['ip'] = ip
        return row, plan


    def _write_remembered_killed_macs(self) -> None:
        """Persist LAN ARP kill MACs only (WinDivert kill uses ``killed_devices`` / ICS profiles)."""
        if not self.remember:
            set_settings('killed', [])
            return
        kept = []
        for mac, entry in list((self.killer.killed or {}).items()):
            device = entry if isinstance(entry, dict) else {'mac': mac}
            try:
                if should_restore_remembered_kill(device, self.scanner):
                    kept.append(mac)
            except Exception:
                continue
        set_settings('killed', kept)


    def _device_with_plan_ip(self, device):
        """Return device dict with resolved IP for the active impairment path."""
        if not isinstance(device, dict):
            return device
        return device_row_for_impairment(
            device, self.scanner, self._impairment_plan_for(device)
        )


    def _refresh_selected_device_impairment_plan(self) -> None:
        """On row select: classify hotspot vs ethernet-console vs regular LAN."""
        dev = self._get_selected_device()
        if not dev or dev.get('admin'):
            self._selected_impairment_mac = None
            self._selected_impairment_plan = None
            return
        mac = str(dev.get('mac') or '').strip()
        plan = self._impairment_plan_for(dev)
        prev_mac = self._selected_impairment_mac
        prev_path = getattr(self._selected_impairment_plan, 'path', None)
        self._selected_impairment_mac = mac
        self._selected_impairment_plan = plan
        if mac != prev_mac or plan.path != prev_path:
            if clumsy_mode_enabled():
                self.log(impairment_status_line(plan), UI_LOG_RESTORE_FG)


    def _killed_profile_key(self, device) -> str:
        pk = self._device_profile_key(device)
        if pk:
            return pk
        return str(device.get('mac') or '').strip()


    def _flow_matches_row(self, device, flow_mac, flow_ip=None) -> bool:
        if not device or not flow_mac or device.get('mac') != flow_mac:
            return False
        want = (flow_ip or '').strip()
        if not want:
            # Same MAC on home LAN + hotspot: never highlight every nickname row.
            peers = [
                d
                for d in self.scanner.devices
                if d.get('mac') == flow_mac and not d.get('admin')
            ]
            return len(peers) <= 1
        return (str(device.get('ip') or '').strip() == want)


    def _flow_matches_active_row(self, device, flow_mac, flow_ip=None) -> bool:
        """Match lag/dupe/kill flows to one table row (MAC + IP)."""
        if flow_ip:
            return self._flow_matches_row(device, flow_mac, flow_ip)
        snap_ip = ''
        if getattr(self, 'lag_active', False) and flow_mac == getattr(self, 'lag_device_mac', None):
            snap = getattr(self, '_lag_device_snapshot', None)
            if isinstance(snap, dict):
                snap_ip = str(snap.get('ip') or '').strip()
        if getattr(self, 'dupe_active', False) and flow_mac == getattr(self, 'dupe_device_mac', None):
            snap = getattr(self, '_dupe_arm_device', None)
            if isinstance(snap, dict):
                snap_ip = str(snap.get('ip') or '').strip()
        if snap_ip:
            return self._flow_matches_row(device, flow_mac, snap_ip)
        return self._flow_matches_row(device, flow_mac, flow_ip)


    def _killed_profile_on(self, device) -> bool:
        pk = self._killed_profile_key(device)
        return bool(pk and self.killed_devices.get(pk, False))


    def _set_killed_profile(self, device, on: bool) -> None:
        pk = self._killed_profile_key(device)
        if pk:
            self.killed_devices[pk] = bool(on)


    def _device_for_kill_profile(self, profile_key: str):
        for d in self.scanner.devices:
            if self._killed_profile_key(d) == profile_key:
                return d
        mac, _prefix = parse_nickname_profile_key(profile_key)
        if mac:
            return self._victim_record_for_mac(mac)
        return None


    def _resolve_flow_start_device(self, device: dict) -> dict:
        """Resolve plan IP + live LAN endpoint before pinning lag/dupe flow identity."""
        dev = self._device_with_plan_ip(dict(device))
        plan = self._impairment_plan_for(dev)
        if not plan.use_arp_mitm or plan.is_ics_downstream:
            return dev
        try:
            from tools.utils import resolve_live_lan_victim

            iface_ip = str(getattr(self.scanner.iface, 'ip', None) or '').strip()
            old_mac = str(dev.get('mac') or '').strip()
            old_ip = str(dev.get('ip') or '').strip()
            resolved, hint = resolve_live_lan_victim(
                dev,
                getattr(self.scanner, 'devices', None) or [],
                iface_ip,
                ping_attempts=1,
            )
            if isinstance(resolved, dict):
                dev.clear()
                dev.update(resolved)
                new_mac = str(dev.get('mac') or '').strip()
                new_ip = str(dev.get('ip') or '').strip()
                if hint:
                    self.log(hint, UI_LOG_VICTIM_BLOCK_FG)
                elif new_ip != old_ip or new_mac != old_mac:
                    self.log(
                        f'Target updated to {new_ip} ({new_mac}) for flow.',
                        UI_LOG_VICTIM_BLOCK_FG,
                    )
                if new_mac and new_mac != old_mac:
                    self._rekey_kill_bookkeeping(old_mac, dev)
                if new_ip != old_ip or new_mac != old_mac:
                    self._migrate_killed_profile_for_device_change(old_mac, old_ip, dev)
        except Exception:
            pass
        return dev


    def _console_historical_ips(self, device) -> set[str]:
        """Saved IPv4s for nickname-linked MACs (Wi‑Fi ↔ Ethernet handoff)."""
        ips: set[str] = set()
        if not isinstance(device, dict):
            return ips
        try:
            from tools.utils import _resolve_allowed_macs
            from networking.nicknames import get_nickname_last_ip_map, parse_nickname_profile_key

            allowed = _resolve_allowed_macs(device)
            if not allowed:
                return ips
            last_map = get_nickname_last_ip_map()
            for key, lip in last_map.items():
                lm, _pfx = parse_nickname_profile_key(str(key))
                if lm not in allowed:
                    continue
                s = str(lip or '').strip()
                if s and _is_valid_ip(s):
                    ips.add(s)
            for mac in allowed:
                s = str(last_map.get(mac) or '').strip()
                if s and _is_valid_ip(s):
                    ips.add(s)
        except Exception:
            pass
        return ips


    def _console_sibling_victims(self, device, victims: list[dict]) -> None:
        """Append nickname-linked Wi‑Fi/Ethernet siblings still in killer.killed."""
        if not isinstance(device, dict):
            return
        try:
            from tools.utils import _resolve_allowed_macs, good_mac

            allowed = {good_mac(m) for m in _resolve_allowed_macs(device) if good_mac(m)}
            keep = good_mac(str(device.get('mac') or ''))
            if not allowed:
                return
            have = {good_mac(str(v.get('mac') or '')) for v in victims if isinstance(v, dict)}
            for emac in list(getattr(self.killer, 'killed', {}).keys()):
                gm = good_mac(str(emac or ''))
                if not gm or gm == keep or gm not in allowed or gm in have:
                    continue
                entry = self._victim_record_for_mac(emac) or {'mac': emac}
                if isinstance(entry, dict):
                    victims.append(dict(entry))
                    have.add(gm)
        except Exception:
            pass


    def _victim_teardown_ips(self, device) -> set[str]:
        """Every IP we may have blocked for this victim (table, plan, ICS resolve)."""
        ips: set[str] = set()
        if not isinstance(device, dict):
            return ips
        dev = self._device_with_plan_ip(dict(device))
        for raw in (
            dev.get('ip'),
            self._flow_stable_victim_ip(dev),
            clumsy_ics_resolve_victim_ip(dev, self.scanner),
        ):
            s = str(raw or '').strip()
            if s and _is_valid_ip(s):
                ips.add(s)
        ips.update(self._console_historical_ips(dev))
        return ips


    def _ics_device_with_resolved_ip(self, device) -> dict:
        row, _plan = self._victim_row(device)
        return row


    def _ics_hotspot_victim_ip(
        self,
        device,
        *,
        lag: bool = False,
        dupe: bool = False,
        pctcut: bool = False,
        mitmshape: bool = False,
    ) -> str:
        """Resolved downstream IP for WinDivert, or '' if not on ICS path."""
        row, plan = self._victim_row(
            device, lag=lag, dupe=dupe, pctcut=pctcut, mitmshape=mitmshape
        )
        if plan.is_ics_downstream:
            return str(row.get('ip') or plan.resolved_ip or '').strip()
        return ''


    def _flow_stable_victim_ip(
        self,
        device,
        *,
        lag: bool = False,
        dupe: bool = False,
        pctcut: bool = False,
        mitmshape: bool = False,
    ) -> str:
        """Pinned ICS IP while a flow runs — avoids gate on wrong address after rescan."""
        if lag and getattr(self, 'lag_active', False):
            ip = (getattr(self, 'lag_device_ip', None) or '').strip()
            if ip:
                return ip
        if dupe and getattr(self, 'dupe_active', False):
            ip = (getattr(self, 'dupe_device_ip', None) or '').strip()
            if ip:
                return ip
        if pctcut and getattr(self, 'percent_cut_active', False):
            ip = (getattr(self, 'percent_cut_device_ip', None) or '').strip()
            if ip:
                return ip
        if mitmshape and getattr(self, 'mitm_shaping_active', False):
            ip = (getattr(self, 'mitm_shaping_device_ip', None) or '').strip()
            if ip:
                return ip
        if isinstance(device, dict):
            return clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
                device.get('ip') or ''
            ).strip()
        return ''


    def _dupe_impairment_is_live(self, device) -> bool:
        """True when click-time preblock or gate actually owns this victim."""
        if not isinstance(device, dict):
            return False
        dev = self._device_with_plan_ip(dict(device))
        plan = self._impairment_plan_for(dev)
        ips = self._victim_teardown_ips(dev)
        if plan.use_windivert:
            gate = getattr(self, '_ics_lag_gate', None)
            if gate is not None and gate.is_running():
                vip = str(getattr(gate, 'victim_ip', '') or '').strip()
                return bool(vip and vip in ips)
            return False
        mac = str(dev.get('mac') or '').strip()
        return bool(mac and mac in getattr(self.killer, 'killed', {}))


    def _victim_record_for_mac(self, mac):
        """
        Victim dict for unkill: same MAC as when killed, but IP refreshed from the current scan
        so ARP restore matches the real host after DHCP / rescan.
        """
        if mac in self.killer.killed:
            victim = dict(self.killer.killed[mac])
            fresh = self._get_device_by_mac(mac, victim.get('ip'))
            if fresh:
                victim['ip'] = fresh['ip']
            return victim
        return None
