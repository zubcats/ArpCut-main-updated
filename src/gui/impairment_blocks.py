"""Apply/clear victim block helpers for impairment (extracted from MainWindow)."""
from __future__ import annotations

from tools.clumsy_inline import (
    clumsy_ics_lag_can_use_windivert,
    clumsy_ics_resolve_victim_ip,
    clumsy_mode_enabled,
    clumsy_windivert_unavailable_reason,
    victim_on_clumsy_ics_subnet,
)
from tools.pfctl import _is_valid_ip
from gui.impairment_shared import (
    UI_LOG_RESTORE_FG,
    UI_LOG_VICTIM_BLOCK_FG,
    _bg_block_ip,
    _bg_unblock_ip,
)


class ImpairmentBlocksMixin:
    def _flow_instant_preblock(
        self, device, direction: str = 'both', *, flow: str = 'Lag'
    ) -> bool:
        """
        Cut victim traffic synchronously on flow toggle — before deferred prep.
        Hotspot: WinDivert pause. Home LAN: immediate ARP poison burst.
        """
        dev = dict(device) if isinstance(device, dict) else {}
        ip = str(dev.get('ip') or '').strip()
        if not ip:
            return False
        plan = self._impairment_plan_for(dev)
        direction = str(direction or 'both').strip().lower()
        if direction not in ('both', 'in', 'out'):
            direction = 'both'
        if plan.use_windivert:
            if not clumsy_ics_lag_can_use_windivert(dev, self.scanner):
                return False
            if clumsy_mode_enabled() and not victim_on_clumsy_ics_subnet(ip):
                rip = str(clumsy_ics_resolve_victim_ip(dev, self.scanner) or '').strip()
                if rip and victim_on_clumsy_ics_subnet(rip):
                    dev['ip'] = rip
                    ip = rip
            if not victim_on_clumsy_ics_subnet(ip):
                return False
            try:
                from tools.ics_windivert_shaper import IcsWinDivertLagGate

                gate = getattr(self, '_ics_lag_gate', None)
                if gate is not None and gate.victim_ip != ip:
                    try:
                        self._stop_ics_lag_gate(join_timeout=0.05)
                    except Exception:
                        pass
                    gate = None
                if gate is not None and gate.is_running():
                    gate.set_direction(direction)
                    if hasattr(gate, 'set_victim_ip'):
                        gate.set_victim_ip(ip)
                    gate.pause_connection()
                else:
                    gate = IcsWinDivertLagGate(ip)
                    gate.start(direction=direction, start_paused=True)
                    self._ics_lag_gate = gate
                if flow == 'Lag':
                    self._lag_ics_preblocked = True
                    self._lag_lan_preblocked = False
                elif flow == 'Dupe':
                    self._dupe_preblocked = True
                return True
            except Exception:
                if flow == 'Lag':
                    self._lag_ics_preblocked = False
                elif flow == 'Dupe':
                    self._dupe_preblocked = False
                return False
        if plan.use_arp_mitm:
            mac = str(dev.get('mac') or '').strip()
            if not mac:
                return False
            try:
                self.killer.router = getattr(self.scanner, 'router', None) or self.killer.router
                self.killer.iface = self.scanner.iface
                self.killer.disable_percent_cut(mac)
                if not self.killer.l2_socket_ready():
                    self.killer.prewarm_l2_socket(join_ms=120)
                if mac in self.killer.killed:
                    self.killer.reassert_poison(dev)
                    self.killer._apply_traffic_cut_sync(dev)
                else:
                    self.killer.kill(dev, wait_after=0.0, traffic_cut=True)
                if flow == 'Lag':
                    self._lag_lan_preblocked = True
                    self._lag_ics_preblocked = False
                    self._lag_net_prepared_mac = mac
                elif flow == 'Dupe':
                    self._dupe_preblocked = True
                return True
            except Exception:
                if flow == 'Lag':
                    self._lag_lan_preblocked = False
                elif flow == 'Dupe':
                    self._dupe_preblocked = False
                return False
        if flow == 'Lag':
            self._lag_ics_preblocked = False
            self._lag_lan_preblocked = False
        elif flow == 'Dupe':
            self._dupe_preblocked = False
        return False


    def _lag_instant_preblock(self, device) -> bool:
        return self._flow_instant_preblock(
            device, getattr(self, 'lag_direction', 'both'), flow='Lag'
        )

    def _pctcut_instant_apply(self, device, cut_pct: int) -> bool:
        """
        Apply the Percent Cut ratio on click — before deferred prep / cross-flow
        teardown. Uses partial cut (not full Kill pause) so low % cuts stay honest.
        """
        self._pctcut_preapplied = False
        dev = dict(device) if isinstance(device, dict) else {}
        ip = str(dev.get('ip') or '').strip()
        if not ip or not _is_valid_ip(ip):
            return False
        try:
            cut_pct = max(1, min(100, int(cut_pct)))
        except Exception:
            cut_pct = 100
        allow_pct = max(0, 100 - cut_pct)
        plan = self._impairment_plan_for(dev)
        if plan.use_windivert or plan.is_ics_downstream:
            if not clumsy_ics_lag_can_use_windivert(dev, self.scanner):
                return False
            if clumsy_mode_enabled() and not victim_on_clumsy_ics_subnet(ip):
                rip = str(clumsy_ics_resolve_victim_ip(dev, self.scanner) or '').strip()
                if rip and victim_on_clumsy_ics_subnet(rip):
                    dev['ip'] = rip
                    ip = rip
            if not victim_on_clumsy_ics_subnet(ip):
                return False
            try:
                if not self._ensure_ics_lag_gate(dev, 'both'):
                    return False
                gate = getattr(self, '_ics_lag_gate', None)
                if gate is None:
                    return False
                if hasattr(gate, 'clear_blocking_pause'):
                    gate.clear_blocking_pause()
                else:
                    gate.set_blocking(False)
                gate.apply_percent_cut(cut_pct)
                self._pctcut_preapplied = True
                return True
            except Exception:
                self._pctcut_preapplied = False
                return False
        if plan.use_arp_mitm:
            mac = str(dev.get('mac') or '').strip()
            if not mac:
                return False
            try:
                self.killer.router = getattr(self.scanner, 'router', None) or self.killer.router
                self.killer.iface = self.scanner.iface
                if not self.killer.l2_socket_ready():
                    self.killer.prewarm_l2_socket(join_ms=120)
                ok = bool(self.killer.apply_percent_cut(dev, pass_percent=allow_pct))
                self._pctcut_preapplied = ok
                return ok
            except Exception:
                self._pctcut_preapplied = False
                return False
        return False


    def _release_dupe_victim_immediate(self, device, *, refresh_context: bool = True) -> None:
        """Restore connectivity on the GUI thread (Lag Switch OFF parity).

        Deferred ``_do_deferred_dupe_clear`` only drops leftover firewall rules;
        waiting for netsh unblock before ``unkill`` left victims cut for 1–3+ s.
        """
        if not isinstance(device, dict):
            return
        device = self._device_with_plan_ip(device)
        plan = self._impairment_plan_for(device)
        if plan.use_windivert or plan.is_ics_downstream or self._ics_gate_matches_device(device):
            try:
                self._ics_emergency_release(device, heal=True)
            except Exception:
                pass
        try:
            self._release_victim_arp_mitm_stack(device, refresh_context=refresh_context)
        except Exception:
            pass
        self._schedule_dupe_off_reinforce(device.get('mac'), device)


    def _apply_victim_block(self, device, direction, **ics_block_kw) -> bool:
        plan = self._impairment_plan_for(device)
        device = self._device_with_plan_ip(device)
        if plan.use_windivert:
            return self._apply_ics_client_block(device, direction, **ics_block_kw)
        if plan.is_ics_downstream and not plan.use_windivert:
            # Hotspot/ethernet-console with no WinDivert: do not pretend Kill/Lag armed.
            try:
                from tools.zubcut_log import app_log

                app_log(
                    'impairment_dead_zone',
                    mac=str(device.get('mac') or ''),
                    ip=str(device.get('ip') or ''),
                    path=getattr(plan, 'path', None),
                )
            except Exception:
                pass
            self.log(
                'Hotspot impairment unavailable — run as Administrator and confirm the '
                'WinDivert bundle is installed, then rescan.',
                'red',
            )
            return False
        if not plan.use_arp_mitm:
            return False
        mac = str(device.get('mac') or '').strip()
        for_lag = bool(ics_block_kw.get('for_lag'))
        for_dupe = bool(ics_block_kw.get('for_dupe'))
        fast_arm = for_lag or for_dupe
        warm_lag = for_lag and self._lag_lan_mitm_warm(device)
        if warm_lag:
            return self._lag_apply_block_warm(device)
        if for_lag and mac and getattr(self, '_lag_net_prepared_mac', None) == mac:
            pass
        else:
            self._ensure_network_context_for_victim(device, fast=fast_arm)
            if for_lag and mac:
                self._lag_net_prepared_mac = mac
        mitm_ok, mitm_reason = self.killer.mitm_prereqs_ok(
            device, ping_attempts=1 if fast_arm else 3
        )
        if not mitm_ok:
            if for_lag:
                self.log(f'Lag MITM blocked: {mitm_reason}', 'red')
            elif for_dupe:
                self.log(f'Dupe MITM blocked: {mitm_reason}', 'red')
            return False
        self.killer.disable_percent_cut(device['mac'])
        wait_after = 0.08 if fast_arm else 2
        if device['mac'] not in self.killer.killed:
            self.killer.kill(device, wait_after=wait_after, traffic_cut=fast_arm)
        elif for_lag or for_dupe:
            # Mid-burst safety — reassert without bumping _op_seq (stale killed[] entry).
            self.killer.reassert_poison(device)
        # block_ip is 4x netsh add (in/out + IPv4/IPv6) — ~1–3 s synchronous. Lag
        # Switch calls _apply_victim_block on every block phase, so a sync call here
        # froze the UI for seconds per cycle. ARP poison above already cuts the
        # victim instantly; firewall layer is a backstop and is safe to defer.
        try:
            iface_name = self.scanner.iface.name if self.scanner.iface else 'en0'
        except Exception:
            iface_name = 'en0'
        _bg_block_ip(iface_name, device.get('ip'), direction)
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(device['mac'])
        self._updateKillButtonState()
        return True


    def _clear_victim_block(self, device):
        plan = self._impairment_plan_for(device)
        device = self._device_with_plan_ip(device)
        if plan.use_windivert:
            if self._clear_ics_client_block(device):
                return
        elif not plan.use_arp_mitm:
            return
        mac = str(device.get('mac') or '').strip()
        if getattr(self, 'lag_active', False) and mac and getattr(self, '_lag_net_prepared_mac', None) == mac:
            pass
        else:
            self._ensure_network_context_for_victim(device)
        _bg_unblock_ip(device.get('ip'))
        if device['mac'] in self.killer.killed:
            try:
                victim = self._victim_record_for_mac(device['mac']) or device
                self.killer.unkill(victim)
            except Exception:
                pass
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(device['mac'])
        self._updateKillButtonState()


    def _clear_explicit_kill_for_flow(self, device) -> None:
        """Drop Kill ON for this victim so Lag/Dupe can arm MITM (shared ARP stack)."""
        if not isinstance(device, dict):
            return
        dev = self._device_with_plan_ip(dict(device))
        mac = str(dev.get('mac') or '').strip()
        if not mac:
            return
        if not self._killed_profile_on(dev) and mac not in getattr(self.killer, 'killed', {}):
            return
        self._set_killed_profile(dev, False)
        victim = self._victim_record_for_mac(mac) or dev
        plan = self._impairment_plan_for(dev)
        ics_mode = bool(plan.is_ics_downstream)
        if (
            getattr(self, 'lag_active', False)
            and plan.use_windivert
            and getattr(self, '_ics_lag_gate', None) is not None
        ):
            gate = self._ics_lag_gate
            if gate is not None and gate.is_running():
                self._sync_killed_devices()
                self._updateKillButtonState()
                return
        if getattr(self, 'lag_active', False) and getattr(self, '_lag_lan_preblocked', False):
            if mac in getattr(self.killer, 'killed', {}):
                self._set_killed_profile(dev, False)
                self._sync_killed_devices()
                self._updateKillButtonState()
                return
        if getattr(self, 'dupe_active', False) and mac and mac == getattr(self, 'dupe_device_mac', None):
            self._set_killed_profile(dev, False)
            self._sync_killed_devices()
            self._updateKillButtonState()
            return
        if getattr(self, 'percent_cut_active', False) and mac and mac == getattr(
            self, 'percent_cut_device_mac', None
        ):
            self._set_killed_profile(dev, False)
            self._sync_killed_devices()
            self._updateKillButtonState()
            return
        if getattr(self, 'dupe_active', False):
            gate = getattr(self, '_ics_lag_gate', None)
            if (
                plan.use_windivert
                and getattr(self, '_dupe_preblocked', False)
                and gate is not None
                and gate.is_running()
            ):
                self._set_killed_profile(dev, False)
                self._sync_killed_devices()
                self._updateKillButtonState()
                return
            if getattr(self, '_dupe_preblocked', False) and mac in getattr(self.killer, 'killed', {}):
                self._set_killed_profile(dev, False)
                self._sync_killed_devices()
                self._updateKillButtonState()
                return
        try:
            _bg_unblock_ip(victim.get('ip'))
            self.killer.unkill(victim, ics_mode=ics_mode)
        except Exception:
            pass
        self._sync_killed_devices()
        self._updateKillButtonState()


    def _clear_explicit_kill_for_dupe(self, device) -> None:
        self._clear_explicit_kill_for_flow(device)


    def _arm_victim_mitm_like_kill(self, device, direction: str, *, flow: str = 'Kill') -> bool:
        """LAN/hotspot MITM arm — same traffic-cut stack as explicit Kill ON."""
        device = self._device_with_plan_ip(dict(device))
        plan = self._impairment_plan_for(device)
        use_windivert = bool(plan.use_windivert)
        if use_windivert:
            from tools.clumsy_inline import victim_on_clumsy_ics_subnet

            device = self._prepare_victim_for_impairment(device, fast=True)
            plan = self._impairment_plan_for(device)
            ip = str(device.get('ip') or plan.resolved_ip or '').strip()
            if not (ip and victim_on_clumsy_ics_subnet(ip)):
                if plan.is_ics_downstream and ip:
                    pass
                else:
                    use_windivert = False
                    self.log(
                        f'{flow}: {ip or "?"} is on home LAN — using ARP MITM '
                        '(PS5 left hotspot / using router Wi‑Fi).',
                        UI_LOG_RESTORE_FG,
                    )
        if use_windivert:
            ok = bool(
                self._apply_ics_client_block(
                    device, direction, for_dupe=(flow == 'Dupe'), for_lag=(flow == 'Lag')
                )
            )
            if not ok:
                reason = clumsy_windivert_unavailable_reason(device)
                self.log(
                    f'{flow} on hotspot needs WinDivert (run ZubCut as Administrator). {reason}',
                    'red',
                )
            return ok
        plan = self._impairment_plan_for(device)
        if not plan.use_arp_mitm:
            return False
        self._ensure_network_context_for_victim(device, fast=True)
        if flow == 'Dupe':
            self._sync_dupe_device_identity(device)
        mac = str(device.get('mac') or '').strip()
        self.killer.router = getattr(self.scanner, 'router', None) or self.killer.router
        self.killer.disable_percent_cut(mac)
        mitm_ok, mitm_reason = self.killer.mitm_prereqs_ok(device, ping_attempts=1)
        if not mitm_ok:
            self.log(f'{flow} MITM blocked: {mitm_reason}', 'red')
            return False
        if mac in self.killer.killed:
            self.killer.reassert_poison(device)
            try:
                self.killer._apply_traffic_cut_sync(device)
            except Exception:
                pass
        else:
            self.killer.kill(device, wait_after=0.08, traffic_cut=True)
        mac = self._rekey_kill_bookkeeping(mac, device)
        fw = self.killer.forwarders.get(mac)
        if not (fw and getattr(fw, 'running', False)):
            self.killer.disable_percent_cut(mac)
            try:
                iface_name = self.scanner.iface.name if self.scanner.iface else 'en0'
            except Exception:
                iface_name = 'en0'
            _bg_block_ip(iface_name, device.get('ip'), direction)
            self.log(
                f'{flow} ON (ARP+firewall) for {device.get("ip", "")} — '
                'Npcap forwarder unavailable; ARP+firewall still active.',
                UI_LOG_VICTIM_BLOCK_FG,
            )
        else:
            try:
                iface_name = self.scanner.iface.name if self.scanner.iface else 'en0'
            except Exception:
                iface_name = 'en0'
            _bg_block_ip(iface_name, device.get('ip'), direction)
            self.log(f'{flow} ON for {device.get("ip", "")}', UI_LOG_VICTIM_BLOCK_FG)
        self._log_mitm_arm_status(device, action=flow)
        self._schedule_mitm_traffic_probe(device, flow=flow)
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(mac, device.get('ip'))
        self._updateKillButtonState()
        return True


    def _arm_dupe_mitm_like_kill(self, device, direction: str) -> bool:
        return self._arm_victim_mitm_like_kill(device, direction, flow='Dupe')


    def _lag_clear_block_only(self, device, direction: str | None = None) -> None:
        """Allow phase on home LAN: drop firewall backstop; resume forwarder pass-through."""
        device = self._device_with_plan_ip(device)
        ip = str(device.get('ip') or '').strip()
        if ip:
            _bg_unblock_ip(ip)
        _ = direction or getattr(self, 'lag_direction', 'both')
        mac = str(device.get('mac') or '').strip()
        if mac and mac in getattr(self.killer, 'killed', {}):
            try:
                self.killer.apply_percent_cut(device, pass_percent=100)
            except Exception:
                pass


    def _lag_apply_block_warm(self, device) -> bool:
        """Block phase while MITM is already armed — poison burst + firewall only."""
        device = self._device_with_plan_ip(device)
        mac = str(device.get('mac') or '').strip()
        if not mac or mac not in self.killer.killed:
            return False
        direction = getattr(self, 'lag_direction', 'both')
        try:
            self.killer.reassert_poison(device)
        except Exception:
            pass
        try:
            self.killer._apply_traffic_cut_sync(device)
        except Exception:
            pass
        try:
            iface_name = self.scanner.iface.name if self.scanner.iface else 'en0'
        except Exception:
            iface_name = 'en0'
        _bg_block_ip(iface_name, device.get('ip'), direction)
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(mac, device.get('ip'))
        self._updateKillButtonState()
        return True


    def _lag_apply_block(self, device):
        """Block phase: WinDivert pause in-place when possible (fast lag cycles on hotspot)."""
        device = self._device_with_plan_ip(device)
        plan = self._impairment_plan_for(device)
        try:
            if plan.use_windivert:
                self._ics_quiesce_killer_mitm(device)
        except Exception:
            pass
        if plan.use_windivert:
            if self._lag_ics_windivert_active(device) and self._lag_ics_set_paused(device, True):
                mac = str(device.get('mac') or '').strip()
                if mac:
                    self._refresh_table_row_for_mac(mac, device.get('ip'))
                return True
            return bool(self._apply_ics_client_block(device, self.lag_direction, for_lag=True))
        if self._lag_lan_mitm_warm(device):
            ok = self._lag_apply_block_warm(device)
        else:
            ok = self._apply_victim_block(device, self.lag_direction, for_lag=True)
        if ok:
            self._schedule_mitm_traffic_probe(device, flow='Lag')
        if not ok:
            self.log(
                f'Lag block missed for {device.get("ip", "")} — retrying… '
                f'(not a Settings problem if Me row IP matches ipconfig)',
                'red',
            )
            self._schedule_lag_block_rearm_retry(device)
        return ok


    def _lag_resolved_victim(self):
        """
        Merge live table row with the lag snapshot. Clumsy rows can briefly disappear during
        rescan/sync, and the ICS IP can update while lag runs — a frozen dict breaks block/unblock.
        """
        mac = getattr(self, 'lag_device_mac', None)
        if not mac:
            return None
        live = self._get_device_by_mac(mac, getattr(self, 'lag_device_ip', None))
        snap = getattr(self, '_lag_device_snapshot', None)
        if snap is not None and snap.get('mac') != mac:
            snap = None
        if not live and not snap:
            return None
        if not live:
            merged = dict(snap) if snap else None
        elif not snap:
            merged = dict(live)
        else:
            merged = dict(live)
            lip = (live.get('ip') or '').strip()
            sip = (snap.get('ip') or '').strip()
            if (not lip) and sip:
                merged['ip'] = sip
        if merged:
            try:
                plan = self._impairment_plan_for(merged)
                if clumsy_mode_enabled() and plan.is_ics_downstream:
                    prepared = self._prepare_victim_for_impairment(merged, fast=True)
                    if isinstance(prepared, dict) and prepared:
                        merged = dict(prepared)
                        new_ip = str(merged.get('ip') or '').strip()
                        if new_ip and self.lag_active:
                            self.lag_device_ip = new_ip
                else:
                    if not self._lag_skip_live_resolve(merged):
                        from tools.utils import resolve_live_lan_victim

                        iface_ip = str(getattr(self.scanner.iface, 'ip', None) or '').strip()
                        resolved, hint = resolve_live_lan_victim(
                            merged,
                            getattr(self.scanner, 'devices', None) or [],
                            iface_ip,
                            ping_attempts=1,
                        )
                        if isinstance(resolved, dict):
                            merged = dict(resolved)
                            new_mac = str(merged.get('mac') or '').strip()
                            if new_mac and new_mac != mac and self.lag_active:
                                self.lag_device_mac = new_mac
                                self.lag_device_ip = merged.get('ip')
                                self._lag_net_prepared_mac = None
                            if hint and self.lag_active:
                                self.log(hint, UI_LOG_VICTIM_BLOCK_FG)
            except Exception:
                pass
        return merged


    def _has_explicit_kill_active(self):
        return any(bool(v) for v in self.killed_devices.values())

    def _release_pctcut_victim_immediate(self, victim) -> None:
        """Stop Percent Cut like Dupe OFF: traffic already resumed; teardown without GUI stalls."""
        if not isinstance(victim, dict):
            return
        victim = self._device_with_plan_ip(victim)
        plan = self._impairment_plan_for(victim)
        mac = str(victim.get('mac') or '').strip()
        ip = str(victim.get('ip') or '').strip()
        if plan.use_windivert or plan.is_ics_downstream or self._ics_gate_matches_device(victim):
            try:
                gate = getattr(self, '_ics_lag_gate', None)
                if gate is not None:
                    if hasattr(gate, 'clear_blocking_pause'):
                        gate.clear_blocking_pause()
                    else:
                        gate.set_blocking(False)
                    gate.apply_percent_cut(0)
            except Exception:
                pass
            if ip and _is_valid_ip(ip):
                _bg_unblock_ip(ip)
            # Drop stray ARP MITM if any; do not emergency-stop WinDivert here —
            # join_timeout on gate.stop freezes OFF. Keep gate warm or stop idle later.
            try:
                if mac and mac in (self.killer.killed or {}):
                    self.killer.unkill(
                        self._victim_record_for_mac(mac) or victim, ics_mode=True
                    )
            except Exception:
                pass
            try:
                # Short join only when nothing else needs the shared gate.
                if not self._ics_windivert_busy(mac or None):
                    self._stop_ics_lag_gate(join_timeout=0.05)
            except Exception:
                pass
            return
        # LAN MITM: pass_all_live already restored traffic; stop sniffer async + unkill.
        try:
            if mac:
                self.killer.disable_percent_cut(mac)
        except Exception:
            pass
        try:
            self._release_victim_arp_mitm_stack(victim, refresh_context=False)
        except Exception:
            pass
        self._schedule_pctcut_off_reinforce(mac, victim)

    def _schedule_pctcut_off_reinforce(self, prev_mac, device) -> None:
        """ARP reinforce only (Dupe OFF parity) — never block the toggle click."""
        if not device or not prev_mac:
            return
        if self._uses_windivert(device) and prev_mac not in self.killer.killed:
            return
        pct_off_seq = self._bump_flow_off_intent('pctcut', prev_mac)
        self._schedule_flow_off_reinforce('pctcut', prev_mac, pct_off_seq, 25, device)
        self._schedule_flow_off_reinforce('pctcut', prev_mac, pct_off_seq, 100, device)

    def _pctcut_instant_resume(self, mac: str | None, ip: str | None = None) -> None:
        """Restore full pass ratio / clear WinDivert cut on the OFF click stack."""
        mac = str(mac or '').strip()
        ip = str(ip or '').strip()
        try:
            gate = getattr(self, '_ics_lag_gate', None)
            if gate is not None:
                if hasattr(gate, 'clear_blocking_pause'):
                    gate.clear_blocking_pause()
                else:
                    gate.set_blocking(False)
                gate.apply_percent_cut(0)
        except Exception:
            pass
        if mac:
            try:
                self.killer.resume_percent_cut_live(mac)
            except Exception:
                pass
        if ip and _is_valid_ip(ip):
            try:
                _bg_unblock_ip(ip)
            except Exception:
                pass
