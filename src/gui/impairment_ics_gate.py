"""ICS / WinDivert gate helpers for impairment (extracted from MainWindow)."""
from __future__ import annotations

from PyQt5.QtCore import QTimer

from tools.clumsy_inline import (
    clumsy_ics_lag_can_use_windivert,
    clumsy_ics_resolve_victim_ip,
    clumsy_windivert_probe_detail,
    clumsy_windivert_unavailable_reason,
    release_ics_victim_block,
    restore_ics_hotspot_connectivity,
    victim_on_clumsy_ics_subnet,
)
from tools.ics_impairment_policy import quiesce_legacy_stack
from gui.impairment_shared import UI_LOG_VICTIM_BLOCK_FG, _bg_unblock_ip


class ImpairmentIcsGateMixin:
    def _ics_windivert_busy(self, mac: str | None = None) -> bool:
        """True if any flow still uses the shared ICS WinDivert gate for this MAC (or any)."""
        if self.lag_active and mac is None:
            return True
        if self.lag_active and mac is not None:
            dev = self._get_device_by_mac(mac, getattr(self, 'lag_device_ip', None))
            if dev and self._flow_matches_active_row(dev, self.lag_device_mac, self.lag_device_ip):
                return True
        if self.dupe_active and mac is None:
            return True
        if self.dupe_active and mac is not None:
            dev = self._get_device_by_mac(mac, getattr(self, 'dupe_device_ip', None))
            if dev and self._flow_matches_active_row(dev, self.dupe_device_mac, self.dupe_device_ip):
                return True
        if self.percent_cut_active and (mac is None or self.percent_cut_device_mac == mac):
            return True
        if self.mitm_shaping_active and (mac is None or self.mitm_shaping_mac == mac):
            return True
        if mac is not None:
            for d in self.scanner.devices:
                if d.get('mac') == mac and self._kill_ui_shows_on(mac, d.get('ip'), d):
                    return True
            return False
        return any(bool(v) for v in self.killed_devices.values())


    def _stop_ics_lag_gate(self, join_timeout: float = 0.12) -> None:
        gate = getattr(self, '_ics_lag_gate', None)
        self._ics_lag_gate = None
        self._ics_windivert_shaper = None
        if gate is not None:
            try:
                if hasattr(gate, 'prepare_stop'):
                    gate.prepare_stop()
                gate.stop(join_timeout=join_timeout)
            except Exception:
                pass


    def _ics_gate_matches_device(self, device) -> bool:
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is None or not isinstance(device, dict):
            return False
        vip = str(getattr(gate, 'victim_ip', None) or '').strip()
        if not vip:
            return False
        return vip in self._victim_teardown_ips(device)


    def _release_victim_arp_mitm_stack(self, device, *, refresh_context: bool = True) -> None:
        """
        Drop LAN ARP MITM, forwarder, and firewall for this victim.
        Safe to call after WinDivert teardown — unkill is a no-op when not armed.
        """
        if not isinstance(device, dict):
            return
        device = self._device_with_plan_ip(dict(device))
        if refresh_context:
            try:
                self._ensure_network_context_for_victim(device, fast=True)
            except Exception:
                pass
        try:
            from tools.utils import good_mac

            target_mac = good_mac(str(device.get('mac') or ''))
        except Exception:
            target_mac = str(device.get('mac') or '').strip()
        ips = self._victim_teardown_ips(device)
        victims: list[dict] = []
        primary = self._victim_record_for_mac(target_mac) or device
        if isinstance(primary, dict):
            victims.append(primary)
        for entry in list((self.killer.killed or {}).values()):
            if not isinstance(entry, dict):
                continue
            try:
                from tools.utils import good_mac as _gm

                emac = _gm(str(entry.get('mac') or ''))
            except Exception:
                emac = str(entry.get('mac') or '').strip()
            eip = str(entry.get('ip') or '').strip()
            if (target_mac and emac == target_mac) or (eip and eip in ips):
                if entry not in victims:
                    victims.append(entry)
        self._console_sibling_victims(device, victims)
        for ip in ips:
            _bg_unblock_ip(ip)
        seen: set[str] = set()
        for victim in victims:
            mac = str(victim.get('mac') or '').strip()
            if not mac or mac in seen:
                continue
            seen.add(mac)
            is_ics = self._is_ics_downstream(victim)
            if is_ics:
                try:
                    self.killer.disable_percent_cut(mac)
                except Exception:
                    pass
            try:
                self.killer.unkill(victim, ics_mode=is_ics)
            except Exception:
                pass
            try:
                self.killer.reinforce_restore(victim, ics_mode=is_ics)
            except Exception:
                pass
        self._ics_teardown_gate_if_idle(target_mac or None)


    def _ics_gate_allow_traffic(self, gate=None) -> None:
        """Resume WinDivert forwarding without clearing percent-cut / shaping state."""
        g = gate if gate is not None else getattr(self, '_ics_lag_gate', None)
        if g is None:
            return
        try:
            if hasattr(g, 'clear_blocking_pause'):
                g.clear_blocking_pause()
            else:
                g.set_blocking(False)
        except Exception:
            pass


    def _ics_unpause_victim(self, device) -> None:
        """Instantly resume live traffic; discard held pause packets (no replay burst)."""
        _ = device
        self._ics_gate_allow_traffic()


    def _ics_quiesce_killer_mitm(self, device) -> None:
        """Drop ARP MITM / firewall / forwarder when WinDivert owns this victim."""
        if not isinstance(device, dict):
            return
        victim = self._device_with_plan_ip(
            self._victim_record_for_mac(str(device.get('mac') or '').strip()) or device
        )
        quiesce_legacy_stack(self.scanner, self.killer, victim)


    def _ics_apply_percent_cut_windivert(self, device, cut_pct: int) -> bool:
        """Hotspot / ethernet-console partial cut via WinDivert (byte budget, not pause / Kill)."""
        device = self._prepare_victim_for_impairment(
            self._device_with_plan_ip(self._ics_device_with_resolved_ip(device)),
            fast=True,
        )
        ip = self._ics_hotspot_victim_ip(device, pctcut=True)
        if not ip:
            return False
        device['ip'] = ip
        self._ics_quiesce_killer_mitm(device)
        if not self._ensure_ics_lag_gate(device, 'both'):
            return False
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is None:
            return False
        try:
            if hasattr(gate, 'clear_blocking_pause'):
                gate.clear_blocking_pause()
            else:
                gate.set_blocking(False)
            gate.apply_percent_cut(cut_pct)
        except Exception:
            return False
        return True


    def _ics_apply_advanced_shaping_windivert(
        self,
        device,
        *,
        du: int,
        dd: int,
        ju: int,
        jd: int,
        lu: int,
        ld: int,
        cu_mbps: float,
        cd_mbps: float,
    ) -> bool:
        """ICS downstream Advanced Lag via WinDivert (not pause / Kill / MITM forwarder)."""
        device = self._prepare_victim_for_impairment(
            self._device_with_plan_ip(self._ics_device_with_resolved_ip(device)),
            fast=True,
        )
        ip = self._ics_hotspot_victim_ip(device, mitmshape=True)
        if not ip:
            return False
        device['ip'] = ip
        self._ics_quiesce_killer_mitm(device)
        if not self._ensure_ics_lag_gate(device, 'both'):
            return False
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is None:
            return False
        try:
            if hasattr(gate, 'clear_blocking_pause'):
                gate.clear_blocking_pause()
            else:
                gate.set_blocking(False)
            gate.apply_shaping_params(du, dd, ju, jd, lu, ld, cu_mbps, cd_mbps)
        except Exception:
            return False
        self._ics_windivert_shaper = gate
        return True


    def _ics_hotspot_windivert_teardown(self, device, *, heal: bool = False) -> None:
        """
        Stop the ICS WinDivert gate so traffic bypasses ZubCut (same packet path as Kill OFF).
        Does not change Kill UI state — use _release_ics_windivert_block for full Kill teardown.
        """
        if not isinstance(device, dict):
            return
        resolved_ip = self._flow_stable_victim_ip(
            device,
            lag=getattr(self, 'lag_active', False),
            dupe=getattr(self, 'dupe_active', False),
        )
        if not resolved_ip:
            resolved_ip = clumsy_ics_resolve_victim_ip(device, self.scanner)
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is not None:
            try:
                gate.set_blocking(False)
                gate.clear_shaping()
                gate.prepare_stop()
            except Exception:
                pass
        self._stop_ics_lag_gate(join_timeout=0.35)
        if heal and resolved_ip:
            # F3: only schedule hotspot heal pulses when victim is actually on
            # the ICS downstream subnet. LAN Kill OFF must not enter this path.
            try:
                on_ics = bool(victim_on_clumsy_ics_subnet(resolved_ip))
            except Exception:
                on_ics = False
            if on_ics:
                victim = dict(device)
                victim['ip'] = resolved_ip
                self._schedule_ics_hotspot_heal(victim)


    def _ics_hotspot_pause_release(self, device, *, heal: bool = False) -> None:
        """
        Hotspot lag allow / traffic resume: Kill-OFF-equivalent (stop gate + unblock IP).
        Leaves killer.killed / killed_devices unchanged when lag was not mirroring Kill.
        """
        if not isinstance(device, dict):
            return
        plan = self._impairment_plan_for(device)
        if not plan.is_ics_downstream:
            return
        device = self._device_with_plan_ip(device)
        self._ics_hotspot_windivert_teardown(device, heal=heal)
        if plan.use_block_ip:
            ip = (
                self._flow_stable_victim_ip(device, lag=True)
                or plan.resolved_ip
                or str(device.get('ip') or '').strip()
            )
            _bg_unblock_ip(ip)


    def _release_ics_windivert_block(self, device, *, heal: bool = True) -> None:
        """Full WinDivert OFF: unpause, stop gate, clear killer bookkeeping, heal PS5 gateway ARP."""
        if not isinstance(device, dict):
            return
        mac = str(device.get('mac') or '').strip()
        self._ics_hotspot_windivert_teardown(device, heal=heal)
        if mac:
            if mac in getattr(self, '_ics_kill_profile_macs', set()):
                self.killer.killed.pop(mac, None)
            self._ics_kill_profile_macs.discard(mac)
            self._set_killed_profile(device, False)


    def _schedule_ics_hotspot_heal(self, device) -> None:
        """Clumsy does not need ARP heal; hotspot + our ARP path needs repeated gateway refresh."""
        if not isinstance(device, dict):
            return
        snap = dict(device)

        def _pulse() -> None:
            try:
                restore_ics_hotspot_connectivity(
                    self.scanner,
                    self.killer,
                    snap,
                    repeats=4,
                )
            except Exception:
                pass

        for delay_ms in (0, 350, 900, 2000):
            QTimer.singleShot(delay_ms, _pulse)


    def _ics_emergency_release(self, device, *, heal: bool = True) -> None:
        """
        Hotspot OFF: WinDivert gate, any stray ARP MITM, and firewall rules for this victim.
        Used when dupe/kill/lag ends (including instant toggle-off before timers fire).

        Plan-drift safe: if the victim hopped LAN ↔ hotspot between ON and OFF
        the current plan no longer matches what we laid down. We still tear down
        whatever ICS state actually exists (gate, _ics_kill_profile_macs,
        WinDivert, firewall) rather than gating on plan.is_ics_downstream.
        LAN ARP Kill (`killer.killed` only) is not ICS — do not steal that OFF.
        """
        if not isinstance(device, dict):
            return
        plan = self._impairment_plan_for(device)
        device = self._device_with_plan_ip(device)
        mac = str(device.get('mac') or '').strip()
        gate_live = self._ics_gate_matches_device(device)
        # Has-state probe: only skip when nothing to clean. If any of these are
        # live we tear them down regardless of the current plan classification.
        has_ics_state = bool(
            gate_live
            or (
                mac
                and (
                    mac in getattr(self, '_ics_kill_profile_macs', set())
                    or self._ics_windivert_busy(mac)
                )
            )
        )
        if not plan.is_ics_downstream and not has_ics_state:
            return
        victim = self._victim_record_for_mac(mac) or device
        # release_ics_victim_block must run BEFORE _release_ics_windivert_block:
        # the latter pops killer.killed[mac] which would make the `mac in killed`
        # guard below always False, leaving any stacked ARP MITM (from kill ON
        # _apply_ics_client_block) running silently after the UI says OFF.
        if mac and mac in self.killer.killed:
            try:
                release_ics_victim_block(self.scanner, self.killer, victim)
            except Exception:
                pass
        self._release_ics_windivert_block(device, heal=heal)
        ip = (
            plan.resolved_ip
            or clumsy_ics_resolve_victim_ip(device, self.scanner)
            or str(device.get('ip') or '').strip()
        )
        _bg_unblock_ip(ip)


    def _ics_teardown_gate_if_idle(self, mac: str | None = None) -> None:
        if not self._ics_windivert_busy(mac):
            self._stop_ics_lag_gate()


    def _ics_victim_impairment_active(self, victim_ip: str) -> bool:
        """True when ZubCut is intentionally pausing this hotspot client (Kill/Dupe/Lag/etc.)."""
        ip = str(victim_ip or '').strip()
        if not ip:
            return False
        if getattr(self, 'lag_active', False):
            lip = (getattr(self, 'lag_device_ip', None) or '').strip()
            if not lip or lip == ip:
                return True
        if getattr(self, 'dupe_active', False):
            dip = (getattr(self, 'dupe_device_ip', None) or '').strip()
            if not dip or dip == ip:
                return True
        if getattr(self, 'percent_cut_active', False):
            dev = self._get_device_by_mac(getattr(self, 'percent_cut_device_mac', None) or '')
            if dev:
                dip = self._flow_stable_victim_ip(dev) or str(dev.get('ip') or '').strip()
                if dip == ip:
                    return True
        if getattr(self, 'mitm_shaping_active', False):
            dev = self._get_device_by_mac(getattr(self, 'mitm_shaping_mac', None) or '')
            if dev:
                dip = self._flow_stable_victim_ip(dev) or str(dev.get('ip') or '').strip()
                if dip == ip:
                    return True
        for _mac, dev in (getattr(self.killer, 'killed', None) or {}).items():
            if not isinstance(dev, dict):
                continue
            dip = clumsy_ics_resolve_victim_ip(dev, self.scanner) or str(dev.get('ip') or '')
            if str(dip).strip() == ip:
                return True
        return False


    def _schedule_ics_windivert_traffic_check(self, victim_ip: str) -> None:
        """
        After Kill ON: if WinDivert sees no traffic, log a hint.
        """
        ip = str(victim_ip or '').strip()
        if not ip:
            return
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is None or gate.victim_ip != ip:
            return
        session = id(gate)
        if getattr(self, '_ics_wd_traffic_warn_session', None) == session:
            return
        self._ics_wd_traffic_warn_session = session
        mac = ''
        dev = self._get_device_by_mac(None, ip)
        if isinstance(dev, dict):
            mac = str(dev.get('mac') or '').strip()

        def _check() -> None:
            gate = getattr(self, '_ics_lag_gate', None)
            if gate is None or gate.victim_ip != ip or not gate.is_running():
                return
            if not self._ics_victim_impairment_active(ip):
                return
            if gate.packets_matched > 0:
                return
            if gate.packets_held > 0:
                return
            layers = gate.active_layers or ()
            seen = gate.packets_seen
            arp_active = bool(mac and mac in self.killer.killed)
            if seen == 0 and isinstance(dev, dict) and self._retry_ics_windivert_capture(dev, ip):
                return
            if seen == 0 and not arp_active:
                self.log(
                    f'WinDivert sees no traffic for {ip} (layers {layers}). '
                    'Run as Administrator; confirm PS5 is on 192.168.137.x / 173.x.',
                    'red',
                )
            elif seen == 0 and arp_active:
                self.log(
                    f'WinDivert idle for {ip}; Kill is still armed.',
                    UI_LOG_VICTIM_BLOCK_FG,
                )

        QTimer.singleShot(4000, _check)


    def _retry_ics_windivert_capture(self, device, ip: str) -> bool:
        """Re-resolve hotspot IP + reopen WinDivert when the gate sees zero packets."""
        ip = str(ip or '').strip()
        if not ip or not isinstance(device, dict):
            return False
        retried = getattr(self, '_ics_wd_retry_ips', None)
        if retried is None:
            retried = set()
            self._ics_wd_retry_ips = retried
        if ip in retried:
            return False
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is None or not gate.is_running():
            return False
        if gate.packets_seen > 0 or gate.packets_matched > 0:
            return False
        try:
            prepared = self._prepare_victim_for_impairment(device, fast=True)
            new_ip = str(prepared.get('ip') or ip).strip()
            if not new_ip:
                return False
            retried.add(ip)
            if new_ip != ip:
                retried.add(new_ip)
            self._stop_ics_lag_gate(join_timeout=0.35)
            if self._ensure_ics_lag_gate(prepared, 'both', start_paused=True):
                g = self._ics_lag_gate
                if g is not None:
                    if hasattr(g, 'pause_connection'):
                        g.pause_connection()
                    else:
                        g.set_blocking(True, mode='pause')
            self.log(
                f'Hotspot Kill: WinDivert saw no traffic for {ip} — retried on '
                f'{new_ip} ({getattr(self.scanner.iface, "name", "?") or "?"})',
                UI_LOG_VICTIM_BLOCK_FG,
            )
            self._schedule_ics_windivert_traffic_check(new_ip)
            return True
        except Exception:
            return False


    def _ensure_ics_lag_gate(
        self, device, direction: str, *, start_paused: bool = False
    ) -> bool:
        plan = self._impairment_plan_for(device)
        if not plan.is_ics_downstream:
            return False
        if not clumsy_ics_lag_can_use_windivert(device, self.scanner):
            return False
        ip_quick = str(device.get('ip') or '').strip() if isinstance(device, dict) else ''
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is not None and gate.is_running() and ip_quick and gate.victim_ip == ip_quick:
            gate.set_direction(direction)
            if hasattr(gate, 'set_victim_ip'):
                gate.set_victim_ip(ip_quick)
            if start_paused:
                gate.pause_connection()
            elif getattr(self, 'percent_cut_active', False):
                pct = self._clamp_percent(self.spinPercentCutMain.value())
                gate.apply_percent_cut(pct)
            elif (
                getattr(self, 'lag_active', False)
                and not getattr(self, '_lag_in_allow_phase', False)
            ):
                gate.pause_connection()
            return True
        if isinstance(device, dict):
            device = self._prepare_victim_for_impairment(device, fast=True)
            plan = self._impairment_plan_for(device)
        ip = self._ics_hotspot_victim_ip(
            device,
            lag=getattr(self, 'lag_active', False),
            dupe=getattr(self, 'dupe_active', False),
            pctcut=getattr(self, 'percent_cut_active', False),
            mitmshape=getattr(self, 'mitm_shaping_active', False),
        )
        if not ip:
            ip = plan.resolved_ip or (
                str(device.get('ip') or '').strip() if isinstance(device, dict) else ''
            )
        if not ip:
            return False
        if isinstance(device, dict):
            device['ip'] = ip
        from tools.ics_windivert_shaper import IcsWinDivertLagGate

        gate = getattr(self, '_ics_lag_gate', None)
        if gate is not None and gate.victim_ip != ip:
            self._stop_ics_lag_gate(join_timeout=0.5)
            gate = None
        if gate is not None and gate.victim_ip == ip:
            if gate.is_running():
                gate.set_direction(direction)
                if hasattr(gate, 'set_victim_ip'):
                    gate.set_victim_ip(ip)
                if start_paused:
                    gate.pause_connection()
                elif getattr(self, 'percent_cut_active', False):
                    pct = self._clamp_percent(self.spinPercentCutMain.value())
                    gate.apply_percent_cut(pct)
                return True
            if getattr(self, 'lag_active', False) or getattr(self, 'dupe_active', False):
                try:
                    self._stop_ics_lag_gate(join_timeout=0.08)
                except Exception:
                    pass
                gate = IcsWinDivertLagGate(ip)
                gate.start(direction=direction, start_paused=start_paused)
                self._ics_lag_gate = gate
                if start_paused or (
                    getattr(self, 'lag_active', False)
                    and not getattr(self, '_lag_in_allow_phase', False)
                ):
                    gate.pause_connection()
                return True
        if gate is not None:
            self._stop_ics_lag_gate(join_timeout=0.5)
        gate = IcsWinDivertLagGate(ip)
        gate.start(direction=direction, start_paused=start_paused)
        self._ics_lag_gate = gate
        if start_paused or (
            getattr(self, 'lag_active', False)
            and not getattr(self, '_lag_in_allow_phase', False)
        ):
            gate.pause_connection()
        if hasattr(gate, 'set_victim_ip'):
            gate.set_victim_ip(ip)
        if not getattr(self, 'lag_active', False) and not getattr(self, 'dupe_active', False):
            self._schedule_ics_windivert_traffic_check(ip)
        return True


    def _apply_ics_client_block(
        self, device, direction, *, for_dupe: bool = False, for_lag: bool = False
    ) -> bool:
        """
        ICS client impairment (all lag methods): pause connection in WinDivert.

        Used for Kill, Dupe, and Lag Switch block. Hotspot is WinDivert-only
        (same as real Clumsy) — no ICS-ARP and no firewall on this path.
        Lag Switch uses WinDivert pause only — do not mirror Kill into killer.killed.
        """
        plan = self._impairment_plan_for(device)
        if not plan.is_ics_downstream:
            return False
        device = self._prepare_victim_for_impairment(self._ics_device_with_resolved_ip(device), fast=True)
        ip = self._ics_hotspot_victim_ip(
            device,
            lag=for_lag,
            dupe=for_dupe,
        ) or plan.resolved_ip or str(device.get('ip') or '').strip()
        if ip:
            device['ip'] = ip
        self.killer.disable_percent_cut(device['mac'])
        windivert_ok = False
        gate = None
        if not clumsy_ics_lag_can_use_windivert(device, self.scanner):
            self.log(
                'Hotspot lag needs WinDivert: '
                + clumsy_windivert_unavailable_reason(device),
                'red',
            )
        else:
            try:
                if for_lag or for_dupe:
                    self._ics_quiesce_killer_mitm(device)
                if self._ensure_ics_lag_gate(
                    device, direction, start_paused=not for_lag
                ):
                    gate = self._ics_lag_gate
                    if gate is not None:
                        if hasattr(gate, 'pause_connection'):
                            gate.pause_connection()
                        else:
                            gate.set_blocking(True, mode='pause')
                        windivert_ok = gate.is_running()
            except OSError as exc:
                detail = clumsy_windivert_probe_detail(ip)
                self.log(
                    f'WinDivert lag failed for {ip}: {exc} [{detail}]',
                    'red',
                )
        if windivert_ok:
            if for_dupe:
                pass
            elif for_lag:
                self._refresh_table_row_for_mac(device['mac'], device.get('ip'))
            else:
                self._ics_kill_profile_macs.add(device['mac'])
                self._set_killed_profile(device, True)
                self._sync_killed_devices()
                self._refresh_table_row_for_mac(device['mac'], device.get('ip'))
                self._updateKillButtonState()
            if not for_lag:
                parts = []
                if gate is not None:
                    cap = getattr(gate, '_capture_desc', '?')
                    n_h = len(getattr(gate, '_handles', []) or [])
                    parts.append(f'WinDivert {cap} h={n_h}')
                self.log(
                    f'Hotspot pause on {ip} ({", ".join(parts) or "active"})',
                    UI_LOG_VICTIM_BLOCK_FG,
                )
            return True
        # Do not tear down a shared gate still used by Lag / Dupe / Percent Cut.
        try:
            self._ics_teardown_gate_if_idle(str(device.get('mac') or '').strip() or None)
        except Exception:
            pass
        self.log(
            'Hotspot block failed — run as Administrator, confirm WinDivert bundle, '
            'then rescan the PS5 on 192.168.137.x / 173.x.',
            'red',
        )
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(device['mac'])
        self._updateKillButtonState()
        return False


    def _clear_ics_client_block(self, device, *, pause_only: bool = False) -> bool:
        if not self._is_ics_downstream(device):
            return False
        mac = str(device.get('mac') or '').strip()
        windivert = clumsy_ics_lag_can_use_windivert(device, self.scanner)
        if windivert:
            if pause_only:
                self._ics_unpause_victim(device)
            else:
                # Unpause/stop WinDivert. Also unwind leftover ARP/firewall
                # from older builds that stacked ICS-ARP on Kill ON.
                self._ics_emergency_release(device, heal=True)
        else:
            self._ics_unpause_victim(device)
            if not pause_only:
                victim = self._victim_record_for_mac(mac) or device
                try:
                    release_ics_victim_block(self.scanner, self.killer, victim)
                except Exception:
                    pass
                _bg_unblock_ip(device.get('ip'))
                self._ics_teardown_gate_if_idle(mac)
        if pause_only:
            if getattr(self, 'lag_active', False):
                self._refresh_table_row_for_mac(mac)
                self._repaint_all_table_rows_for_hover()
            else:
                self._sync_killed_devices()
                self._refresh_table_row_for_mac(mac)
                self._updateKillButtonState()
            return True
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(mac)
        self._updateKillButtonState()
        return True
