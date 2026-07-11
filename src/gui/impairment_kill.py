"""Kill flow engine (extracted from MainWindow)."""
from __future__ import annotations

from PyQt5.QtCore import QSize, QTimer, QEventLoop
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

from networking.nicknames import parse_nickname_profile_key
from tools.clumsy_inline import (
    clumsy_ics_lag_can_use_windivert,
    clumsy_ics_resolve_victim_ip,
    clumsy_mode_enabled,
    clumsy_windivert_probe_detail,
    clumsy_windivert_unavailable_reason,
    release_ics_victim_block,
)
from tools.ics_impairment_policy import impairment_status_line
from tools.pfctl import _is_valid_ip
from tools.utils_gui import get_settings
from gui.impairment_shared import (
    UI_LOG_RESTORE_FG,
    UI_LOG_VICTIM_BLOCK_FG,
    _bg_block_ip,
    _bg_unblock_ip,
)


class ImpairmentKillMixin:
    def _device_row_blocked_chrome(self, device):
        """
        Kill-row styling: active lag/dupe victim, or explicit Kill ON for this subnet row.
        Same MAC on home LAN vs hotspot are separate profiles — do not paint all rows red.
        """
        if not device or device.get('admin'):
            return False
        mac = device['mac']
        if getattr(self, 'lag_active', False) and self._flow_matches_active_row(
            device, self.lag_device_mac, getattr(self, 'lag_device_ip', None)
        ):
            return not getattr(self, '_lag_in_allow_phase', False)
        if getattr(self, 'dupe_active', False) and self._flow_matches_active_row(
            device, self.dupe_device_mac, getattr(self, 'dupe_device_ip', None)
        ):
            return True
        if getattr(self, 'percent_cut_active', False) and self._flow_matches_active_row(
            device,
            getattr(self, 'percent_cut_device_mac', None),
            getattr(self, 'percent_cut_device_ip', None),
        ):
            return True
        pk = self._killed_profile_key(device)
        if pk and pk in getattr(self, '_kill_pending_profiles', set()):
            return True
        # Honor the user's intent (_killed_profile_on) instead of the ARP-thread
        # state (mac in killer.killed). The button already uses the intent flag
        # via _kill_ui_shows_on, so the previous behavior left the row repaint
        # racing the ARP worker thread — the user saw "KILL: ON" on the button
        # but the row stayed un-highlighted until the worker spawned + first
        # _send_packet completed (which on a cold Npcap socket can be 0.5–2 s).
        # If the kill actually fails the WinDivert/LAN branches clear the
        # killed_profile so the row de-highlights instantly too.
        return self._killed_profile_on(device)


    def _paint_flow_start_ui(self, kind: str, device=None) -> None:
        """Instant flow feedback on click — no network / ARP / full-table work."""
        if kind in ('lag', 'dupe', 'kill', 'pctcut', 'all'):
            if kind in ('lag', 'all'):
                self._updateLagSwitchButtonState()
            if kind in ('dupe', 'all'):
                self._updateDupeButtonState()
            if kind in ('pctcut', 'all'):
                self._updatePercentCutButtonState()
            self._updateKillButtonState(fast=True)
            self._sync_inline_flow_controls_enabled()
        if device is not None:
            self._repaint_device_table_rows(device)
        self._flush_gui_events()


    def kill(self):
        """
        Apply ARP spoofing to selected device
        """
        # Mirror killAll's cross-flow stop set so the legacy/API path can't
        # stack on top of a lag/dupe/pctcut/MITM-shape already running on the
        # same victim (would leave _op_seq mismatched and ARP poison silently
        # exiting). See start/stop symmetry audit findings A1.
        self.stopLagSwitch()
        self.stopDupe(log=False)
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)
        self.stop_mitm_shaping(log=False)
        self._await_mitm_teardown_thread()
        if not self.connected():
            return
        
        if not self.tableScan.selectedItems():
            self.log('No device selected', 'red')
            return

        device = self.current_index()
        if device.get('admin'):
            self.log('Cannot kill Router / Me', UI_LOG_VICTIM_BLOCK_FG)
            return
        resolved = clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
            device.get('ip') or ''
        ).strip()
        if resolved:
            device = dict(device)
            device['ip'] = resolved
        if not _is_valid_ip(device.get('ip') or ''):
            self.log('Target has no IP yet — enable Internet sharing and rescan.', 'red')
            return

        if self._kill_ui_shows_on(device['mac'], device.get('ip'), device):
            self.log('Device is already killed', 'red')
            return

        if self._uses_windivert(device):
            device = self._prepare_victim_for_impairment(device, fast=True)
            if not self._apply_victim_block(device, 'both'):
                return
            self._set_killed_profile(device, True)
        else:
            self._prepare_victim_for_impairment(device, fast=False)
            self.killer.kill(device)
            try:
                iface_name = self.scanner.iface.name if self.scanner.iface else 'en0'
            except Exception:
                iface_name = 'en0'
            _bg_block_ip(iface_name, device.get('ip'), 'both')
            self._set_killed_profile(device, True)
        self._sync_killed_devices()
        self._write_remembered_killed_macs()
        self.log('Killed ' + device['ip'], UI_LOG_VICTIM_BLOCK_FG)
        self._updateKillButtonState()
        
        self.showDevices()
    
    # @check_connection

    def unkill(self):
        """
        Disable ARP spoofing on the selected device (internal / API).
        Clears lag switch, dupe burst, percent cut and MITM shaping for that flow.
        """
        # Mirror unkillAll: stop every flow on the same victim so killer.unkill
        # doesn't race a still-running MitmForwarder / WinDivert gate. See
        # start/stop symmetry audit finding A2.
        self.stopLagSwitch()
        self.stopDupe(log=False)
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)
        self.stop_mitm_shaping(log=False)
        self._await_mitm_teardown_thread()
        if not self.connected():
            return
        
        if not self.tableScan.selectedItems():
            self.log('No device selected', 'red')
            return

        device = self.current_index()
            
        if not self._kill_ui_shows_on(device['mac'], device.get('ip'), device):
            self.log('Device is already unkilled', 'red')
            return

        victim = self._victim_record_for_mac(device['mac']) or device
        plan = self._impairment_plan_for(victim)
        if plan.is_ics_downstream:
            self._clear_victim_block(victim)
            self._ics_teardown_gate_if_idle(device['mac'])
        else:
            self._ensure_network_context_for_victim(victim)
            _bg_unblock_ip(victim.get('ip'))
            self.killer.unkill(victim)
        self._set_killed_profile(device, False)
        self._sync_killed_devices()
        self._write_remembered_killed_macs()
        self.log('Unkilled ' + device['ip'], UI_LOG_RESTORE_FG)

        self._updateKillButtonState()
        self.showDevices()
    
    # @check_connection

    def killAll(self):
        """
        Kill all scanned devices except admins
        """
        self.stopLagSwitch()
        self.stopDupe(log=False)
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)
        self.stop_mitm_shaping(log=False)
        self._await_mitm_teardown_thread()
        if not self.connected():
            return
        
        for d in self.scanner.devices:
            if d.get('admin'):
                continue
            if self._uses_windivert(d):
                prepared = self._prepare_victim_for_impairment(d, fast=True)
                self._apply_victim_block(prepared, 'both')
                self._set_killed_profile(prepared, True)
            else:
                self._prepare_victim_for_impairment(d, fast=False)
                self.killer.kill(d)
                try:
                    iface = self.scanner.iface.name if self.scanner.iface else 'en0'
                except Exception:
                    iface = 'en0'
                _bg_block_ip(iface, d.get('ip'), 'both')
                self._set_killed_profile(d, True)
        self._sync_killed_devices()
        self._write_remembered_killed_macs()
        self.log('Killed All devices', UI_LOG_VICTIM_BLOCK_FG)

        self.showDevices()

    # @check_connection

    def unkillAll(self):
        """
        Unkill all killed devices except admins.
        Clears lag switches and dupe bursts.
        """
        self.stopLagSwitch()
        self.stopDupe(log=False)
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)
        self.stop_mitm_shaping(log=False)
        self._await_mitm_teardown_thread()
        if not self.connected():
            return
        
        victims_before = [dict(v) for v in self.killer.killed.values()]
        for d in self.scanner.devices:
            if self._is_ics_downstream(d):
                try:
                    self._clear_victim_block(d)
                except Exception:
                    pass
        self._ics_teardown_gate_if_idle()
        for v in victims_before:
            if self._impairment_plan_for(v).is_ics_downstream:
                continue
            _bg_unblock_ip(v.get('ip'))
        self.killer.unkill_all(self.scanner)
        for victim in victims_before:
            mac = victim.get('mac')
            if not mac:
                continue
            if self._uses_windivert(victim):
                continue
            # OFF-only reinforcement for bulk unkill (same cadence as per-device kill OFF).
            self.killer.reinforce_restore(victim)
            off_seq = self._bump_flow_off_intent('all', mac)
            self._schedule_flow_off_reinforce('all', mac, off_seq, 25, victim)
            self._schedule_flow_off_reinforce('all', mac, off_seq, 100, victim)
        self.killed_devices.clear()
        self._sync_killed_devices()
        self._write_remembered_killed_macs()
        self.log('Unkilled All devices', UI_LOG_RESTORE_FG)

        self._updateKillButtonState()
        self.showDevices()


    def _toggle_start_blocked(self, requested_kind, device=None):
        ctrl = getattr(self, '_impairment', None)
        if ctrl is not None:
            return ctrl.toggle_start_blocked(requested_kind, device)
        active_kind = self._active_toggle_kind()
        if active_kind and active_kind != requested_kind:
            if (
                requested_kind in ('dupe', 'lag')
                and active_kind == 'kill'
                and device
                and self._killed_profile_on(device)
            ):
                # Deferred lag/dupe arm clears Kill on this victim (shared ARP stack).
                return False
            self.log(
                f'{self._toggle_kind_label(active_kind)} is active. Turn it off first.',
                UI_LOG_VICTIM_BLOCK_FG,
            )
            return True
        return False


    def toggleKill(self, source='unknown'):
        if not self.connected():
            return
        active_explicit = [pk for pk, on in self.killed_devices.items() if bool(on)]
        device = self._get_selected_device()
        # If one victim is currently Kill-ON and table selection moved, pressing Kill should
        # still turn that victim OFF instead of accidentally turning ON another device.
        if device is None and len(active_explicit) == 1:
            device = self._device_for_kill_profile(active_explicit[0])
        if not device:
            self.log('No device selected', 'red')
            return
        if device['admin']:
            self.log('Cannot kill admin device', UI_LOG_VICTIM_BLOCK_FG)
            return

        mac = device['mac']
        row_pk = self._killed_profile_key(device)
        self._reconcile_stale_kill_profile(device)
        current_ui_on = self._kill_ui_shows_on(mac, device.get('ip'), device)
        if not current_ui_on and len(active_explicit) == 1 and active_explicit[0] != row_pk:
            # Selection drifted to a different row while one kill victim is active.
            victim = self._device_for_kill_profile(active_explicit[0])
            if victim:
                device = victim
                mac = device['mac']
            current_ui_on = self._kill_ui_shows_on(mac, device.get('ip'), device)
        next_state = not current_ui_on
        shaping_mac = str(getattr(self, 'mitm_shaping_mac', None) or '').strip()
        shaping_ip = str(getattr(self, 'mitm_shaping_device_ip', None) or '').strip()
        sel_ip = str(device.get('ip') or '').strip()
        if (
            next_state
            and getattr(self, 'mitm_shaping_active', False)
            and (
                (shaping_mac and shaping_mac != mac)
                or (shaping_ip and sel_ip and shaping_ip != sel_ip)
            )
        ):
            self.stop_mitm_shaping(log=True)
            self.log(
                'Advanced lag stopped — select the live PS5 row (Wi‑Fi .165), not a stale Ethernet IP.',
                UI_LOG_RESTORE_FG,
            )
            return
        if next_state and self._toggle_start_blocked('kill'):
            return
        import time as _tk_time
        _tk_t0 = _tk_time.perf_counter()
        pk = self._killed_profile_key(device)
        if pk:
            pending = getattr(self, '_kill_pending_profiles', set())
            if next_state:
                pending.add(pk)
            else:
                pending.discard(pk)
            self._kill_pending_profiles = pending
        self._set_killed_profile(device, next_state)
        _tk_t1 = _tk_time.perf_counter()
        self._paint_flow_start_ui('kill', device)
        _tk_t4 = _tk_time.perf_counter()
        dev = dict(device)
        on = next_state
        src = source
        if on:
            try:
                plan = self._impairment_plan_for(dev)
                if clumsy_mode_enabled() and plan.is_ics_downstream:
                    dev = self._prepare_victim_for_impairment(dev, fast=True)
                    rip = self._ics_hotspot_victim_ip(dev) or str(dev.get('ip') or '').strip()
                    if rip:
                        dev['ip'] = rip
            except Exception:
                pass
            try:
                self._flow_instant_preblock(dev, 'both', flow='Kill')
            except Exception:
                pass
        self._schedule_kill_command(mac, dev, turn_on=on, source=src)
        if bool(get_settings('debug_kill_timing')):
            _tk_t5 = _tk_time.perf_counter()
            try:
                direction = 'ON' if next_state else 'OFF'
                self.log(
                    f'[TOGGLE-KILL {direction}] profile={int((_tk_t1-_tk_t0)*1000)}ms '
                    f'paint={int((_tk_t4-_tk_t1)*1000)}ms '
                    f'schedule={int((_tk_t5-_tk_t4)*1000)}ms '
                    f'total={int((_tk_t5-_tk_t0)*1000)}ms',
                    'gray',
                )
            except Exception:
                pass


    def _schedule_kill_command(self, mac, device, turn_on, source='unknown'):
        """Paint optimistic Kill UI first; run Npcap/ARP work on the next event-loop tick."""
        dev = dict(device)
        QTimer.singleShot(
            0,
            lambda m=str(mac), d=dev, on=bool(turn_on), src=str(source): self._run_kill_command(
                m, d, on, src
            ),
        )


    def _run_kill_command(self, mac, device, turn_on, source='unknown'):
        """Immediate explicit command path: one click => one kill/unkill command."""
        import time as _kill_time
        _kill_dbg = bool(get_settings('debug_kill_timing'))
        _kill_t0 = _kill_time.perf_counter()
        _kill_marks: list[tuple[str, float]] = []

        def _mark(label: str) -> None:
            if _kill_dbg:
                _kill_marks.append((label, _kill_time.perf_counter()))

        _mark('enter')
        if turn_on:
            if getattr(self, '_kill_teardown_mac', None) == mac:
                self._kill_teardown_mac = None
                self._kill_teardown_ip = None
        else:
            self._kill_teardown_mac = mac
            self._kill_teardown_ip = device.get('ip')
            gate = getattr(self, '_impairment', None)
            if gate is not None:
                gate.teardown.begin('kill', mac)
        teardown_off = not turn_on
        try:
            snapshot_map = getattr(self, '_kill_device_snapshot', None)
            if snapshot_map is None:
                snapshot_map = {}
                self._kill_device_snapshot = snapshot_map
            snapshot_map[mac] = dict(device)
            actual_on = mac in self.killer.killed
            next_seq = int(self._kill_intent_seq.get(mac, 0)) + 1
            self._kill_intent_seq[mac] = next_seq
            my_seq = next_seq

            def _superseded() -> bool:
                return int(self._kill_intent_seq.get(mac, 0)) != my_seq

            if turn_on and not self._killed_profile_on(device):
                return
            kill_applied = False
            if turn_on:
                if clumsy_mode_enabled():
                    plan = self._impairment_plan_for(device)
                    if plan.is_ics_downstream and not clumsy_ics_lag_can_use_windivert(
                        device, self.scanner
                    ):
                        self.log(
                            'Kill on hotspot needs WinDivert: '
                            + clumsy_windivert_unavailable_reason(device),
                            'red',
                        )
                        self._set_killed_profile(device, False)
                        self._sync_killed_devices()
                        self._updateKillButtonState()
                        self._repaint_device_table_rows(device)
                        return
                _mark('crossflow_start')
                if self.lag_active and self.lag_device_mac == mac:
                    self.stopLagSwitch(refresh_dialog=True)
                if self.dupe_active and self.dupe_device_mac == mac:
                    self.stopDupe(log=False)
                    self._flush_pending_dupe_clear_sync()
                if self.percent_cut_active and self.percent_cut_device_mac == mac:
                    self.stopPercentCut(log=False)
                elif self._percent_cut_backend_active(mac, device.get('ip')):
                    try:
                        self._release_pctcut_victim_immediate(device)
                    except Exception:
                        pass
                if self.mitm_shaping_active and self.mitm_shaping_mac == mac:
                    self.stop_mitm_shaping(log=False)
                    self._await_mitm_teardown_thread()
                _mark('crossflow_done')
                # Always re-arm on explicit Kill ON. Skipping when actual_on was true
                # caused "works once then never again" if killer.killed still held the
                # victim while the UI showed OFF (partial unkill / profile desync).
                if device:
                    if not _is_valid_ip(device.get('ip') or ''):
                        self.log('Target has no IP yet — enable sharing and rescan.', 'red')
                    elif self._uses_windivert(device):
                        _mark('windivert_start')
                        device = self._prepare_victim_for_impairment(device, fast=True)
                        resolved_ip = (
                            self._ics_hotspot_victim_ip(device)
                            or str(device.get('ip') or '').strip()
                        )
                        if resolved_ip:
                            device['ip'] = resolved_ip
                        gate = getattr(self, '_ics_lag_gate', None)
                        if (
                            turn_on
                            and gate is not None
                            and gate.is_running()
                            and str(gate.victim_ip or '').strip() == resolved_ip
                        ):
                            _mark('windivert_instant')
                            # Preblock opened WinDivert; still run full hotspot Kill stack (ICS-ARP + profile).
                            kill_applied = bool(self._apply_ics_client_block(device, 'both'))
                        else:
                            kill_applied = bool(self._apply_victim_block(device, 'both'))
                        _mark('windivert_done')
                        if kill_applied:
                            self.log('Kill ON for ' + device['ip'], UI_LOG_VICTIM_BLOCK_FG)
                        elif turn_on:
                            self._ics_emergency_release(device, heal=False)
                            ip = clumsy_ics_resolve_victim_ip(device, self.scanner)
                            detail = clumsy_windivert_probe_detail(ip)
                            self.log(
                                f'Kill failed — WinDivert: {detail}',
                                'red',
                            )
                    elif turn_on and mac in self.killer.killed:
                        _mark('lan_instant')
                        try:
                            self.killer.reassert_poison(device)
                            self.killer._apply_traffic_cut_sync(device)
                        except Exception:
                            pass
                        try:
                            iface_name = self.scanner.iface.name if self.scanner.iface else 'en0'
                        except Exception:
                            iface_name = 'en0'
                        _bg_block_ip(iface_name, device.get('ip'), 'both')
                        kill_applied = True
                        self.log(
                            'Kill ON for ' + str(device.get('ip') or ''),
                            UI_LOG_VICTIM_BLOCK_FG,
                        )
                    else:
                        _mark('lan_start')
                        self._reconcile_network_adapter(log=True)
                        self._ensure_network_context_for_victim(device, fast=False)
                        mac = str(device.get('mac') or mac).strip() or mac
                        _mark('lan_ensure_net_done')
                        self.killer.router = getattr(self.scanner, 'router', None) or self.killer.router
                        self.killer.disable_percent_cut(mac)
                        _mark('lan_disable_pctcut_done')
                        self._refresh_victim_mac_from_system_arp(device)
                        mitm_ok, mitm_reason = self.killer.mitm_prereqs_ok(device, ping_attempts=3)
                        if not mitm_ok:
                            # One more pass after full topology refresh (cold ARP / wrong NIC).
                            try:
                                self.scanner.refresh_local_topology()
                                self._refresh_router_mac_from_system_arp()
                                self._refresh_victim_mac_from_system_arp(device)
                                self.killer.router = (
                                    getattr(self.scanner, 'router', None) or self.killer.router
                                )
                                mitm_ok, mitm_reason = self.killer.mitm_prereqs_ok(
                                    device, ping_attempts=3
                                )
                            except Exception:
                                pass
                        if not mitm_ok:
                            self.log(
                                f'Kill ON failed: {mitm_reason}',
                                'red',
                            )
                            lip = str(device.get('ip') or '').strip()
                            lmac = str(device.get('mac') or '').strip()
                            if lip or lmac:
                                self.log(
                                    f'Kill target checked: {lip or "?"} ({lmac or "no MAC"}) — '
                                    'if that is not your PS5 right now, rescan and select the live row.',
                                    UI_LOG_RESTORE_FG,
                                )
                            kill_applied = False
                        else:
                            self.killer.kill(device, wait_after=0.08)
                            mac = self._rekey_kill_bookkeeping(mac, device)
                            _mark('lan_killer_kill_done')
                            fw = self.killer.forwarders.get(mac)
                            if not (fw and getattr(fw, 'running', False)):
                                # Npcap capture failed but ARP poison is live — same
                                # ARP+firewall stack Lag/Dupe use (forwarder is best-effort).
                                self.killer.disable_percent_cut(mac)
                                try:
                                    iface_name = (
                                        self.scanner.iface.name if self.scanner.iface else 'en0'
                                    )
                                except Exception:
                                    iface_name = 'en0'
                                _bg_block_ip(iface_name, device.get('ip'), 'both')
                                _mark('lan_bg_block_ip_done')
                                self._log_mitm_arm_status(device, action='Kill')
                                self.log(
                                    'Kill ON (ARP+firewall) for '
                                    + str(device.get('ip') or '')
                                    + ' — Npcap forwarder unavailable; ARP+firewall still active.',
                                    UI_LOG_VICTIM_BLOCK_FG,
                                )
                                kill_applied = True
                                self._schedule_mitm_traffic_probe(device, flow='Kill')
                            else:
                                self._log_mitm_arm_status(device, action='Kill')
                                try:
                                    iface_name = (
                                        self.scanner.iface.name if self.scanner.iface else 'en0'
                                    )
                                except Exception:
                                    iface_name = 'en0'
                                _bg_block_ip(iface_name, device.get('ip'), 'both')
                                _mark('lan_bg_block_ip_done')
                                self.log('Kill ON for ' + device['ip'], UI_LOG_VICTIM_BLOCK_FG)
                                kill_applied = True
                                self._schedule_mitm_traffic_probe(device, flow='Kill')
            else:
                # B1: mirror Kill ON's cross-flow stop set — if any of the other
                # flows are still running on this victim (toggle-blocked logic
                # should have prevented it but be defensive), tear them down
                # before unkill so killer.unkill doesn't race a live forwarder.
                if self.lag_active and self.lag_device_mac == mac:
                    self.stopLagSwitch(refresh_dialog=True)
                if self.dupe_active and self.dupe_device_mac == mac:
                    self.stopDupe(log=False)
                    self._flush_pending_dupe_clear_sync()
                if self.percent_cut_active and self.percent_cut_device_mac == mac:
                    if str(source or '') != 'pctcut_auto_off_kill':
                        self.stopPercentCut(log=False)
                elif self._percent_cut_backend_active(mac, device.get('ip')):
                    try:
                        self._release_pctcut_victim_immediate(device)
                    except Exception:
                        pass
                if self.mitm_shaping_active and self.mitm_shaping_mac == mac:
                    self.stop_mitm_shaping(log=False)
                    self._await_mitm_teardown_thread()
                victim = self._victim_record_for_mac(mac) or device
                if victim:
                    # A3-A5: if the victim hopped hotspot↔LAN between ON and OFF,
                    # the current plan no longer matches what we laid down. Run
                    # the ICS teardown defensively first (safe no-op when nothing
                    # ICS is live). Only run the LAN teardown when the device is
                    # NOT on the ICS path — running killer.unkill(ics_mode=False)
                    # for an ICS victim cancels the fast ICS restore worker that
                    # _ics_emergency_release just scheduled (it bumps _op_seq)
                    # and emits 1.5 s of LAN-router ARPs on the hotspot NIC
                    # (killer.unkill default refresh_router=True picks the LAN
                    # gateway via route fallback — see killer.py:123-126).
                    self._ics_emergency_release(victim, heal=True)
                    try:
                        self._release_victim_arp_mitm_stack(victim)
                    except Exception:
                        pass
                    self.log('Kill OFF for ' + str(victim.get('ip', '')), UI_LOG_RESTORE_FG)
                    # OFF-only delayed reinforcement; guarded by intent_seq so stale callbacks no-op.
                    self._schedule_kill_off_reinforce(mac, my_seq, 25)
                    self._schedule_kill_off_reinforce(mac, my_seq, 100)

            if turn_on and kill_applied and _superseded():
                try:
                    victim = self._victim_record_for_mac(mac) or device
                    if victim:
                        self.killer.unkill(victim)
                except Exception:
                    pass
                kill_applied = False

            _mark('tail_start')
            if not _superseded():
                self._set_killed_profile(device, bool(kill_applied) if turn_on else False)
                self._sync_killed_devices()
                _mark('tail_sync_killed_devices_done')
                self._write_remembered_killed_macs()
                _mark('tail_write_remembered_done')
                self._updateKillButtonState()
                self._update_scan_count_status()
                self._refresh_table_row_for_mac(mac, device.get('ip'))
                self._repaint_all_table_rows_for_hover()
                try:
                    app = QApplication.instance()
                    if app is not None:
                        app.processEvents(QEventLoop.ExcludeUserInputEvents)
                except Exception:
                    pass
            _mark('tail_done')
        finally:
            if teardown_off and getattr(self, '_kill_teardown_mac', None) == mac:
                self._kill_teardown_mac = None
                self._kill_teardown_ip = None
                gate = getattr(self, '_impairment', None)
                if gate is not None:
                    gate.teardown.end('kill')
            try:
                pk = self._killed_profile_key(device)
                if pk:
                    self._kill_pending_profiles.discard(pk)
            except Exception:
                pass
            if _kill_dbg and _kill_marks:
                try:
                    parts = []
                    prev_t = _kill_t0
                    for label, t in _kill_marks:
                        parts.append(f'{label}+{int((t - prev_t) * 1000)}ms')
                        prev_t = t
                    total_ms = int((_kill_time.perf_counter() - _kill_t0) * 1000)
                    direction = 'ON' if turn_on else 'OFF'
                    self.log(
                        f'[KILL-TIMING {direction} total={total_ms}ms] ' + ' '.join(parts),
                        'gray',
                    )
                except Exception:
                    pass


    def _schedule_kill_off_reinforce(self, mac, intent_seq, delay_ms):
        """Delayed OFF reinforcement that self-cancels if intent changed."""
        def _cb():
            current_seq = int(self._kill_intent_seq.get(mac, 0))
            snapshot = (getattr(self, '_kill_device_snapshot', None) or {}).get(mac)
            victim = self._victim_record_for_mac(mac) or snapshot
            ui_on = self._killed_profile_on(victim) if victim else False
            if current_seq != int(intent_seq) or ui_on:
                return
            if not victim:
                return
            try:
                plan = self._impairment_plan_for(victim)
                if plan.is_ics_downstream:
                    if mac in self.killer.killed:
                        release_ics_victim_block(self.scanner, self.killer, victim)
                    elif mac not in getattr(self, '_ics_kill_profile_macs', set()):
                        return
                    if self._ics_windivert_busy(mac):
                        return
                    if plan.use_block_ip:
                        _bg_unblock_ip(victim.get('ip'))
                    self._ics_teardown_gate_if_idle(mac)
                else:
                    self._ensure_network_context_for_victim(victim)
                    self.killer.unkill(victim)
                    self.killer.reinforce_restore(victim)
            except Exception:
                pass

        QTimer.singleShot(max(0, int(delay_ms)), _cb)


    def _bump_flow_off_intent(self, kind, mac):
        key = (kind, mac)
        next_seq = int(self._flow_off_intent_seq.get(key, 0)) + 1
        self._flow_off_intent_seq[key] = next_seq
        return next_seq


    def _schedule_flow_off_reinforce(self, kind, mac, intent_seq, delay_ms, device_snapshot):
        """Delayed OFF-only reinforcement for lag/dupe/unkill-all."""
        def _cb():
            key = (kind, mac)
            current_seq = int(self._flow_off_intent_seq.get(key, 0))
            if current_seq != int(intent_seq):
                return
            if kind == 'lag' and self.lag_active and self.lag_device_mac == mac:
                return
            if kind == 'dupe' and self.dupe_active and self.dupe_device_mac == mac:
                return
            if kind == 'pctcut' and self.percent_cut_active and self.percent_cut_device_mac == mac:
                return
            if kind == 'mitmshape' and self.mitm_shaping_active and self.mitm_shaping_mac == mac:
                return
            victim = self._victim_record_for_mac(mac) or device_snapshot
            if not victim:
                return
            try:
                plan = self._impairment_plan_for(victim)
                if plan.is_ics_downstream:
                    if mac not in self.killer.killed and mac not in getattr(
                        self, '_ics_kill_profile_macs', set()
                    ):
                        return
                    if mac in self.killer.killed:
                        release_ics_victim_block(self.scanner, self.killer, victim)
                    if plan.use_block_ip:
                        _bg_unblock_ip(victim.get('ip'))
                    self._ics_teardown_gate_if_idle(mac)
                else:
                    self._ensure_network_context_for_victim(victim)
                    self.killer.unkill(victim)
                    self.killer.reinforce_restore(victim)
            except Exception:
                pass

        QTimer.singleShot(max(0, int(delay_ms)), _cb)


    def _kill_ui_shows_on(self, mac, ip=None, device=None):
        """Kill button state for this table row (subnet profile), not every row with same MAC."""
        if device is None:
            device = self._get_device_by_mac(mac, ip) or {'mac': mac, 'ip': ip or ''}
        if getattr(self, '_dupe_restoring_after_stop', False) and self._flow_matches_row(
            device,
            getattr(self, '_dupe_restoring_mac', None),
            getattr(self, '_dupe_restoring_ip', None),
        ):
            return self._killed_profile_on(device)
        if getattr(self, '_lag_restoring_after_stop', False) and self._flow_matches_row(
            device,
            getattr(self, '_lag_restoring_mac', None),
            getattr(self, '_lag_restoring_ip', None),
        ):
            return self._killed_profile_on(device)
        if getattr(self, '_kill_teardown_mac', None) == mac:
            if not self._flow_matches_row(
                device, mac, getattr(self, '_kill_teardown_ip', None)
            ):
                return False
            return self._killed_profile_on(device)
        return self._killed_profile_on(device)


    def _kill_toggle_pending_for_mac(self, mac: str | None) -> bool:
        mac = str(mac or '').strip()
        if not mac:
            return False
        for pk in getattr(self, '_kill_pending_profiles', set()):
            pm, _pfx = parse_nickname_profile_key(pk)
            if pm == mac or pk == mac:
                return True
        return False


    def _any_explicit_kill_profile_for_mac(self, mac: str | None) -> bool:
        mac = str(mac or '').strip()
        if not mac:
            return False
        for d in self.scanner.devices:
            if d.get('mac') == mac and self._killed_profile_on(d):
                return True
        for pk, on in self.killed_devices.items():
            if not on:
                continue
            pm, _pfx = parse_nickname_profile_key(pk)
            if pm == mac or pk == mac:
                return True
        return False


    def _killer_mac_key(self, mac: str | None) -> str | None:
        """Resolve killer.killed / forwarders key (MAC casing may differ from profile keys)."""
        from tools.utils import good_mac

        want = good_mac(str(mac or '').strip())
        if not want:
            return None
        killed = getattr(self.killer, 'killed', {}) or {}
        if want in killed:
            return want
        for key in killed:
            if good_mac(str(key)) == want:
                return str(key)
        forwarders = getattr(self.killer, 'forwarders', {}) or {}
        if want in forwarders:
            return want
        for key in forwarders:
            if good_mac(str(key)) == want:
                return str(key)
        return None


    def _explicit_kill_backend_live(self, mac: str | None, device=None) -> bool:
        """True when explicit Kill (not lag/dupe/pctcut) still has live network state."""
        from tools.utils import good_mac

        mac_n = good_mac(str(mac or '').strip())
        if not mac_n:
            return False
        ics_macs = {good_mac(m) for m in getattr(self, '_ics_kill_profile_macs', set())}
        if mac_n in ics_macs:
            gate = getattr(self, '_ics_lag_gate', None)
            if gate is not None and gate.is_running():
                return True
            if self._killer_mac_key(mac_n):
                return True
        killer_key = self._killer_mac_key(mac_n)
        if killer_key:
            # ARP poison in killer.killed is the primary cut; forwarder is optional.
            return True
        return False


    def _reconcile_stale_kill_profile(self, device) -> bool:
        """Clear ghost Kill ON when the UI profile outlived the backend (e.g. after idle)."""
        if not device:
            return False
        pk = self._killed_profile_key(device)
        if not pk or pk in getattr(self, '_kill_pending_profiles', set()):
            return False
        if not self._killed_profile_on(device):
            return False
        mac = str(device.get('mac') or '').strip()
        if self._explicit_kill_backend_live(mac, device):
            return False
        self._set_killed_profile(device, False)
        self.log('Kill state reset (was out of sync).', UI_LOG_RESTORE_FG)
        return True


    def _sync_killed_devices(self):
        """
        Sync Kill-toggle bookkeeping with live backend state.

        In-flight toggles stay latched via ``_kill_pending_profiles``. When the
        profile says ON but nothing is actually cutting traffic anymore, clear the
        ghost state so Kill is usable again after idle.
        """
        pending = getattr(self, '_kill_pending_profiles', set())
        for pk in list(self.killed_devices.keys()):
            if not self.killed_devices.get(pk):
                continue
            mac, _pfx = parse_nickname_profile_key(pk)
            if not mac and '|' not in pk:
                mac = pk
            if not mac:
                self.killed_devices.pop(pk, None)
                continue
            if pk in pending:
                continue
            if self._explicit_kill_backend_live(mac):
                continue
            # Clear ghost ICS Kill profiles when WinDivert/ARP backend is gone.
            try:
                from tools.utils import good_mac

                mac_n = good_mac(str(mac or '').strip())
                ics = getattr(self, '_ics_kill_profile_macs', None)
                if isinstance(ics, set) and mac_n:
                    ics.discard(mac_n)
                    ics.discard(mac)
            except Exception:
                pass
            self.killed_devices[pk] = False


    def _set_kill_button_idle_look(self):
        """Icon + compact width for Kill: OFF (matches Lag/Dupe footprint)."""
        self.btnKill.setIcon(self._btn_kill_icon)
        self.btnKill.setIconSize(QSize(56, 56))
        self.btnKill.setMinimumWidth(130)


    def _set_kill_button_active_look(self):
        """
        Long status text needs the full cell width; the skull icon squeezes the label
        sideways when lag/dupe/kill-on strings are shown.
        """
        self.btnKill.setIcon(QIcon())
        self.btnKill.setMinimumWidth(1)


    def _updateKillButtonState(self, *, fast: bool = False):
        device = self._get_selected_device()
        if not device:
            self._set_kill_button_idle_look()
            self.btnKill.setText('Kill: OFF')
            self.btnKill.setStyleSheet(self.BUTTON_NORMAL_STYLE)
            if getattr(self, '_btn_kill_tooltip_static', None):
                self.btnKill.setToolTip(self._btn_kill_tooltip_static)
            return

        mac = device['mac']
        base_tip = getattr(self, '_btn_kill_tooltip_static', None)
        if self.lag_active and self._flow_matches_active_row(
            device, self.lag_device_mac, getattr(self, 'lag_device_ip', None)
        ):
            lag_key = getattr(self, '_shortcut_label_lag', 'M')
            self._set_kill_button_active_look()
            self.btnKill.setText(f'■ LAGGING\n(Press {lag_key} to turn off)')
            self.btnKill.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
            if base_tip:
                self.btnKill.setToolTip(
                    base_tip
                    + ' While lag switch is running for this device, this stops lag and restores traffic (it does not turn Kill on).'
                )
            return
        if self.dupe_active and self._flow_matches_active_row(
            device, self.dupe_device_mac, getattr(self, 'dupe_device_ip', None)
        ):
            dupe_key = getattr(self, '_shortcut_label_dupe', 'P')
            self._set_kill_button_active_look()
            self.btnKill.setText(f'■ DUPE\n(Press {dupe_key} to turn off)')
            self.btnKill.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
            if base_tip:
                self.btnKill.setToolTip(
                    base_tip
                    + ' While Dupe is running for this device, this stops the burst (it does not turn Kill on).'
                )
            return
        if base_tip and not fast:
            plan = self._impairment_plan_for(device)
            tip = base_tip
            if clumsy_mode_enabled() and not device.get('admin'):
                tip += f' Path: {impairment_status_line(plan)}'
            self.btnKill.setToolTip(tip)
        elif base_tip:
            self.btnKill.setToolTip(base_tip)
        is_active = self._kill_ui_shows_on(mac, device.get('ip'), device)
        if is_active:
            kill_key = getattr(self, '_shortcut_label_kill', 'L')
            self._set_kill_button_active_look()
            self.btnKill.setText(f'■ KILL: ON\n(Press {kill_key} to turn off)')
            self.btnKill.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self._set_kill_button_idle_look()
            self.btnKill.setText('Kill: OFF')
            self.btnKill.setStyleSheet(self.BUTTON_NORMAL_STYLE)


    def _enqueue_kill_off_only(self, mac, device):
        """After lag/dupe stop: execute an explicit OFF command immediately."""
        self._set_killed_profile(device, False)
        self._updateKillButtonState()
        dev = dict(device)
        self._schedule_kill_command(mac, dev, turn_on=False, source='enqueue_off_only')
