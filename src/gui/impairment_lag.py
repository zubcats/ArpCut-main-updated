"""Lag Switch flow engine (extracted from MainWindow)."""
from __future__ import annotations

import time

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from tools.clumsy_inline import clumsy_ics_lag_can_use_windivert, clumsy_ics_resolve_victim_ip
from tools.pfctl import _is_valid_ip
from gui.impairment_shared import (
    UI_LOG_RESTORE_FG,
    UI_LOG_VICTIM_BLOCK_FG,
    _bg_block_ip,
    _bg_unblock_ip,
    _focus_widget_absorbs_letter_key,
    format_countdown_ms,
)


class ImpairmentLagMixin:
    def _updateLagSwitchButtonState(self):
        """Update lag switch button based on whether it's active for selected device."""
        if self.lag_active and self.lag_device_mac:
            key = getattr(self, '_shortcut_label_lag', 'M')
            self.btnLagSwitch.setText(f'■ LAGGING (Press {key} to turn off)')
            self.btnLagSwitch.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnLagSwitch.setText('Lag Switch')
            self.btnLagSwitch.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self._sync_inline_flow_controls_enabled()
    

    def _shortcut_global_lag(self, *, from_button: bool = False):
        """Lag toggle while app is foreground, regardless of active sub-window."""
        if not from_button:
            if not self._app_window_is_foreground():
                return
            if _focus_widget_absorbs_letter_key(QApplication.focusWidget()):
                return
        if self.lag_active and self.lag_device_mac:
            lag_edge = 'stop'
            if self._ignore_duplicate_toggle_edge('lag', self.lag_device_mac, lag_edge):
                return
            self.stopLagSwitch()
            return
        device = self._get_selected_device()
        if device is None:
            self.log('No device selected', 'red')
            return
        if device['admin']:
            self.log('Cannot lag admin device', UI_LOG_VICTIM_BLOCK_FG)
            return
        if self._toggle_start_blocked('lag', device):
            return
        lag_edge = 'start'
        if self._ignore_duplicate_toggle_edge('lag', device['mac'], lag_edge):
            return
        lag_ms, normal_ms, direction = self._lag_inline_values()
        self.applyLagSwitchSettings(lag_ms, normal_ms, direction)
        self.startLagSwitch(device)


    def applyLagSwitchSettings(self, block_ms, release_ms, direction):
        self.lag_block_ms = block_ms
        self.lag_release_ms = release_ms
        self.lag_direction = direction
        if self.lag_active:
            allow = getattr(self, '_lag_in_allow_phase', False)
            dur = release_ms if allow else block_ms
            self._lag_schedule_phase(dur)
            if allow:
                dev = self._lag_resolved_victim()
                if dev:
                    self._lag_apply_allow_phase_sync(dev)
            self._tick_lag_countdown()


    def _refresh_lag_timing_from_dialog(self):
        """Keep lag settings in sync with always-visible inline controls."""
        try:
            lag_ms, normal_ms, direction = self._lag_inline_values()
            self.applyLagSwitchSettings(lag_ms, normal_ms, direction)
        except Exception:
            pass


    def _sync_lag_timing_values_from_ui(self) -> None:
        """Read inline lag timings without rescheduling or toggling pause mid phase-transition."""
        try:
            lag_ms, normal_ms, direction = self._lag_inline_values()
            self.lag_block_ms = lag_ms
            self.lag_release_ms = normal_ms
            self.lag_direction = direction
        except Exception:
            pass


    def _lag_inline_values(self):
        return self.lagSpinMain.value(), self.normalSpinMain.value(), self._direction_from_checks(
            self.lagDirBoth, self.lagDirIncoming, self.lagDirOutgoing
        )


    def startLagSwitch(self, device):
        device = self._resolve_flow_start_device(dict(device))
        if not _is_valid_ip(device.get('ip') or ''):
            self.log('Target has no IP yet — cannot start lag.', 'red')
            return
        if self._toggle_start_blocked('lag', device):
            return
        mac = str(device.get('mac') or '').strip()
        if not mac:
            self.log('Target has no MAC yet — rescan after PS5 Wi‑Fi/Ethernet change.', 'red')
            return
        self.lag_device_mac = mac
        self.lag_device_ip = device.get('ip')
        snap = dict(device)
        self._lag_device_snapshot = snap
        self._lag_net_prepared_mac = None
        self.lag_active = True
        self._sync_lag_timing_values_from_ui()
        self.btnLagSwitch.setText('■ LAGGING')
        self.btnLagSwitch.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        dir_text = {'both': 'all', 'in': 'incoming', 'out': 'outgoing'}[self.lag_direction]
        self.log(
            f'Lag switch ON: {self.lag_block_ms}ms lag ({dir_text}) / {self.lag_release_ms}ms normal',
            UI_LOG_VICTIM_BLOCK_FG,
        )
        self._paint_flow_start_ui('lag', device)
        self._lag_phase_arming = True
        self.lblLagCountdownMain.setVisible(True)
        self._set_countdown_label(self.lblLagCountdownMain, 'Arming…')
        self._lag_countdown_timer.start()

        self._lag_ics_preblocked = False
        self._lag_lan_preblocked = False
        try:
            self._begin_cut_analysis_session(snap, flow='Lag')
        except Exception:
            pass
        preblocked = False
        try:
            preblocked = bool(self._lag_instant_preblock(snap))
        except Exception:
            pass
        if preblocked:
            self._lag_net_prepared_mac = mac
            try:
                self._lag_phase_begin_block(dict(snap))
            except Exception:
                pass

        self._lag_start_gen = int(getattr(self, '_lag_start_gen', 0)) + 1
        lag_gen = self._lag_start_gen

        def _lag_deferred_start():
            if getattr(self, '_shutting_down', False):
                return
            if not self.lag_active or int(getattr(self, '_lag_start_gen', 0)) != lag_gen:
                return
            if self.dupe_active:
                self.stopDupe(refresh_dialog=True, log=False)
                if self._dupe_pending_clear or getattr(self, '_dupe_clear_future', None):
                    self._flush_pending_dupe_clear_sync(max_wait_ms=200)
                self._drop_dupe_restoring_banner()
            if self.mitm_shaping_active:
                self.stop_mitm_shaping(log=False)
            if self.percent_cut_active:
                self.stopPercentCut(log=False)
            work_mac = mac
            work_dev = dict(device)
            work_snap = dict(snap)
            preblocked = bool(getattr(self, '_lag_ics_preblocked', False))
            lan_preblocked = bool(getattr(self, '_lag_lan_preblocked', False))
            try:
                if preblocked and self._ics_stack_is_warm():
                    rip = (
                        clumsy_ics_resolve_victim_ip(work_snap, self.scanner)
                        or str(work_snap.get('ip') or '').strip()
                    )
                    if rip:
                        work_snap['ip'] = rip
                        self.lag_device_ip = rip
                elif lan_preblocked and self._lan_mitm_stack_is_warm():
                    self._refresh_victim_mac_from_system_arp(work_snap)
                else:
                    work_snap = self._prepare_victim_for_impairment(work_snap, fast=True)
                plan = self._impairment_plan_for(work_snap)
                if not plan.use_windivert:
                    self._refresh_victim_mac_from_system_arp(work_snap)
                live_mac = str(work_snap.get('mac') or '').strip()
                live_ip = str(work_snap.get('ip') or '').strip()
                if live_mac:
                    work_mac = live_mac
                    self.lag_device_mac = live_mac
                if live_ip:
                    self.lag_device_ip = live_ip
            except Exception as exc:
                self._lag_abort_start(f'Lag failed: {exc}')
                return
            plan = self._impairment_plan_for(work_snap)
            gate = getattr(self, '_ics_lag_gate', None)
            if plan.use_windivert:
                live_ip = str(work_snap.get('ip') or '').strip()
                if gate is not None and gate.is_running():
                    if live_ip and hasattr(gate, 'set_victim_ip') and gate.victim_ip != live_ip:
                        gate.set_victim_ip(live_ip)
                    gate.set_direction(self.lag_direction)
                    if not getattr(self, '_lag_in_allow_phase', False):
                        gate.pause_connection()
                elif not preblocked:
                    if not self._apply_ics_client_block(
                        work_snap, self.lag_direction, for_lag=True
                    ):
                        self._lag_abort_start(
                            'Lag failed: could not pause hotspot traffic — rescan target'
                        )
                        return
            else:
                if lan_preblocked:
                    poison_mac = str(work_snap.get('mac') or '').strip()
                    if poison_mac:
                        try:
                            self.killer.reassert_poison(work_snap)
                        except Exception:
                            pass
                    try:
                        iface_name = self.scanner.iface.name if self.scanner.iface else 'en0'
                    except Exception:
                        iface_name = 'en0'
                    _bg_block_ip(iface_name, work_snap.get('ip'), self.lag_direction)
                else:
                    mitm_ok, mitm_reason = self.killer.mitm_prereqs_ok(work_snap, ping_attempts=1)
                    if not mitm_ok:
                        self._lag_abort_start(f'Lag failed: {mitm_reason}')
                        return
                    if not self._arm_victim_mitm_like_kill(
                        work_snap, self.lag_direction, flow='Lag'
                    ):
                        self._lag_abort_start('Lag failed: could not arm MITM — rescan target')
                        return
            self._clear_explicit_kill_for_flow(work_snap)
            self._lag_net_prepared_mac = work_mac
            try:
                iface = self.scanner.iface
                self.log(
                    f'Lag via {iface.name} ({getattr(iface, "ip", "") or "?"}) → {work_snap.get("ip", "")}',
                    'gray',
                )
            except Exception:
                pass

            if not self.lag_active or self.lag_device_mac != work_mac:
                if self.lag_active and work_mac and self.lag_device_mac != work_mac:
                    self.log(
                        'Lag aborted: target identity changed after Wi‑Fi/Ethernet handoff — '
                        'rescan and select the live PS5 row.',
                        'red',
                    )
                    self.stopLagSwitch(refresh_dialog=True, log=False)
                else:
                    self._lag_abort_start('Lag aborted before first block phase')
                return
            cur = self._lag_resolved_victim() or work_dev
            if getattr(self, '_lag_phase_arming', False):
                self._refresh_lag_timing_from_dialog()
                self._lag_phase_begin_block(cur)
            else:
                self._schedule_lag_start_reassert(work_mac)
            self._schedule_cut_analysis_if_enabled(cur or work_snap, flow='Lag')
            self._refresh_flow_toggle_ui(fast=True)
            self._repaint_device_table_rows(cur)

        QTimer.singleShot(0, _lag_deferred_start)


    def _lag_abort_start(self, message: str) -> None:
        """Drop optimistic lag UI when deferred arm fails."""
        self._lag_phase_arming = False
        self.lag_active = False
        self.lag_device_mac = None
        self.lag_device_ip = None
        self._lag_device_snapshot = None
        self._lag_net_prepared_mac = None
        self._lag_ics_preblocked = False
        self._lag_lan_preblocked = False
        self._stop_lag_countdown()
        self.btnLagSwitch.setText('Lag Switch')
        self.btnLagSwitch.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self.log(message, 'red')
        self._refresh_flow_toggle_ui()


    def _lag_reassert_poison(self, device) -> None:
        """Poison burst only — never restart the ARP worker (see killer.reassert_poison)."""
        if not self.lag_active or not isinstance(device, dict):
            return
        plan = self._impairment_plan_for(device)
        if not plan.use_arp_mitm:
            return
        device = self._device_with_plan_ip(device)
        mac = str(device.get('mac') or '').strip()
        if not mac:
            return
        try:
            if mac in self.killer.killed:
                self.killer.reassert_poison(device)
            else:
                self._lag_apply_block(device)
        except Exception:
            pass


    def _schedule_lag_start_reassert(self, mac):
        """Quick ON reasserts so lag takes effect immediately despite ARP/firewall race timing."""
        gen = int(getattr(self, '_lag_reassert_gen', 0)) + 1
        self._lag_reassert_gen = gen

        def _reassert():
            if int(getattr(self, '_lag_reassert_gen', 0)) != gen:
                return
            if not self.lag_active or self.lag_device_mac != mac or self._lag_in_allow_phase:
                return
            dev = self._lag_resolved_victim()
            if not dev:
                return
            self._lag_reassert_poison(dev)

        QTimer.singleShot(0, _reassert)
        QTimer.singleShot(40, _reassert)
        QTimer.singleShot(110, _reassert)


    def _schedule_lag_block_rearm_retry(self, device) -> None:
        """Retry block once when ping/ARP race fails mid-cycle (allow phase just unkill'd)."""
        if not self.lag_active or self._lag_in_allow_phase or not isinstance(device, dict):
            return
        mac = str(device.get('mac') or '').strip()
        if not mac or self.lag_device_mac != mac:
            return
        gen = int(getattr(self, '_lag_reassert_gen', 0)) + 1
        self._lag_reassert_gen = gen

        def _retry():
            if int(getattr(self, '_lag_reassert_gen', 0)) != gen:
                return
            if not self.lag_active or self._lag_in_allow_phase or self.lag_device_mac != mac:
                return
            dev = self._lag_resolved_victim() or device
            if not dev:
                return
            if self._lag_apply_block(dev):
                self._schedule_lag_start_reassert(mac)

        QTimer.singleShot(120, _retry)
        QTimer.singleShot(320, _retry)


    def _drop_lag_restoring_banner(self):
        """Clear lag stop restoring flags after teardown (Kill UI / dialog)."""
        self._lag_restoring_after_stop = False
        self._lag_restoring_mac = None
        gate = getattr(self, '_impairment', None)
        if gate is not None:
            gate.teardown.end('lag')
        dlg = getattr(self, 'lag_switch_dialog', None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg.refresh_toggle_state()
            except Exception:
                pass


    def _lag_ics_windivert_active(self, device) -> bool:
        plan = self._impairment_plan_for(device)
        return bool(
            isinstance(device, dict)
            and plan.use_windivert
            and clumsy_ics_lag_can_use_windivert(device, self.scanner)
        )


    def _lag_ics_set_paused(self, device, paused: bool) -> bool:
        """Lag Switch on hotspot: toggle WinDivert pause only (no Kill bookkeeping)."""
        if not self._lag_ics_windivert_active(device):
            return False
        try:
            if paused:
                if not self._ensure_ics_lag_gate(device, self.lag_direction):
                    return False
                gate = self._ics_lag_gate
                if gate is None:
                    return False
                gate.set_direction(self.lag_direction)
                if hasattr(gate, 'pause_connection'):
                    gate.pause_connection()
                else:
                    gate.clear_shaping()
                    gate.set_blocking(True, mode='pause')
                return True
            self._ics_gate_allow_traffic()
            return True
        except Exception:
            return False


    def _lag_ics_force_unpause(self) -> None:
        """Resume ICS WinDivert traffic for lag allow phase (no device/IP gate match required)."""
        self._ics_gate_allow_traffic()


    def _lag_bump_phase_seq(self) -> int:
        self._lag_phase_seq = int(getattr(self, '_lag_phase_seq', 0)) + 1
        return self._lag_phase_seq


    def _lag_lan_mitm_warm(self, device) -> bool:
        """True when Lag ON already armed ARP MITM for this victim (allow = unblock only)."""
        if not self.lag_active or not isinstance(device, dict):
            return False
        mac = str(device.get('mac') or '').strip()
        if not mac or mac != getattr(self, 'lag_device_mac', None):
            return False
        plan = self._impairment_plan_for(device)
        if plan.use_windivert or not plan.use_arp_mitm:
            return False
        if mac not in self.killer.killed:
            return False
        # Stay warm for every block/allow cycle once lag has armed MITM (not only first prep).
        return getattr(self, '_lag_net_prepared_mac', None) == mac or bool(self.lag_active)


    def _lag_skip_live_resolve(self, device) -> bool:
        """
        During lag, ARP cache shows poisoned MAC and many PS5s ignore ICMP — skip per-phase ping.
        Avoids false 'did not answer ping' spam on allow transitions and when turning lag OFF.
        """
        if not self.lag_active or not isinstance(device, dict):
            return False
        mac = str(device.get('mac') or '').strip()
        if not mac or mac != str(getattr(self, 'lag_device_mac', None) or '').strip():
            return False
        plan = self._impairment_plan_for(device)
        if plan.use_windivert:
            return bool(
                getattr(self, '_lag_ics_preblocked', False)
                or getattr(self, '_ics_lag_gate', None) is not None
            )
        return mac in getattr(self.killer, 'killed', {})


    def _lag_ics_resume_allow_phase(self, device) -> None:
        """
        Allow window on hotspot: resume WinDivert pause in-place (fast lag cycles).
        Home LAN: warm MITM — firewall off only, ARP worker keeps running.
        """
        if not isinstance(device, dict):
            return
        plan = self._impairment_plan_for(device)
        if not plan.is_ics_downstream:
            if self._lag_lan_mitm_warm(device):
                self._lag_clear_block_only(device)
            else:
                self._clear_victim_block(device)
            return
        device = self._device_with_plan_ip(device)
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is not None:
            try:
                gate.set_direction(self.lag_direction)
                self._ics_gate_allow_traffic(gate)
            except Exception:
                pass
        if not self._ensure_ics_lag_gate(device, self.lag_direction):
            self._ics_gate_allow_traffic()
            return
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is not None:
            try:
                gate.set_direction(self.lag_direction)
                self._ics_gate_allow_traffic(gate)
            except Exception:
                pass
        ip = (
            self._flow_stable_victim_ip(device, lag=True)
            or clumsy_ics_resolve_victim_ip(device, self.scanner)
            or str(device.get('ip') or '').strip()
        )
        plan = self._impairment_plan_for(device)
        if plan.use_block_ip:
            _bg_unblock_ip(ip)


    def _lag_apply_allow_phase_sync(self, device) -> None:
        """Main-thread allow: must run immediately so a queued block job cannot skip release."""
        if not self.lag_active or not isinstance(device, dict):
            return
        try:
            self._lag_ics_resume_allow_phase(device)
        except Exception:
            pass


    def _lag_schedule_phase(self, duration_ms: int) -> None:
        """Single-shot phase timer (block or allow) — same precision model as Dupe."""
        ms = max(1, int(duration_ms))
        self._lag_phase_deadline = time.monotonic() + ms / 1000.0
        self._lag_phase_advance_pending = False
        self._lag_phase_end_timer.stop()
        self._lag_phase_end_timer.start(ms)


    def _lag_request_phase_advance(self) -> None:
        """Coalesce duplicate advance requests (countdown + timer)."""
        if not self.lag_active:
            return
        if getattr(self, '_lag_phase_advance_pending', False):
            return
        self._lag_phase_advance_pending = True
        QTimer.singleShot(0, self._lag_do_phase_advance)


    def _lag_phase_end_timer_fired(self) -> None:
        if not self.lag_active:
            return
        self._lag_do_phase_advance()


    def _lag_do_phase_advance(self, *, force: bool = False) -> None:
        self._lag_phase_advance_pending = False
        if not self.lag_active:
            return
        if not force and time.monotonic() + 0.02 < float(
            getattr(self, '_lag_phase_deadline', 0.0)
        ):
            return
        self._lag_phase_end_timer.stop()
        device = self._lag_resolved_victim()
        if not device:
            self.stopLagSwitch()
            return
        self._lag_device_snapshot = dict(device)
        if self._lag_in_allow_phase:
            self._lag_phase_begin_block(device)
        else:
            self._lag_phase_begin_allow(device)


    def _cancel_lag_block_reassert(self) -> None:
        self._lag_reassert_gen = int(getattr(self, '_lag_reassert_gen', 0)) + 1


    def lag_remaining_ms(self):
        if not self.lag_active:
            return None
        return max(0, int((self._lag_phase_deadline - time.monotonic()) * 1000))

    @staticmethod
    def _lag_countdown_label(allow_phase: bool, rem_ms) -> str:
        """Countdown for block (lag) and allow (normal) phases — same format as Dupe."""
        _ = allow_phase
        if rem_ms is None:
            return ''
        if rem_ms <= 0:
            return 'Time left: 0.00s'
        return format_countdown_ms(rem_ms)


    def _arm_lag_phase_countdown(self) -> None:
        self._lag_countdown_timer.start()
        self._tick_lag_countdown()


    def _stop_lag_countdown(self) -> None:
        self._lag_countdown_timer.stop()
        self.lblLagCountdownMain.setVisible(False)
        self.lblLagCountdownMain.setText('')
        dlg = getattr(self, 'lag_switch_dialog', None)
        if dlg is not None:
            try:
                dlg.set_lag_countdown(None, False)
            except Exception:
                pass

    @staticmethod
    def _set_countdown_label(lbl, text: str) -> None:
        if lbl.text() != text:
            lbl.setText(text)

    def _tick_lag_countdown(self) -> None:
        if not self.lag_active:
            self._stop_lag_countdown()
            return
        if getattr(self, '_lag_phase_arming', False):
            self.lblLagCountdownMain.setVisible(True)
            self._set_countdown_label(self.lblLagCountdownMain, 'Arming…')
            dlg = getattr(self, 'lag_switch_dialog', None)
            if dlg is not None and dlg.isVisible():
                try:
                    dlg.set_lag_countdown(None, False)
                except Exception:
                    pass
            return
        rem = self.lag_remaining_ms()
        allow = bool(getattr(self, '_lag_in_allow_phase', False))
        if rem is not None and rem <= 0:
            self.lblLagCountdownMain.setVisible(True)
            self._set_countdown_label(self.lblLagCountdownMain, 'Time left: 0.00s')
            dlg = getattr(self, 'lag_switch_dialog', None)
            if dlg is not None and dlg.isVisible():
                try:
                    dlg.set_lag_countdown(0, allow)
                except Exception:
                    pass
            # Backup when the single-shot phase timer fails to fire (stuck block).
            self._lag_phase_end_timer.stop()
            if not getattr(self, '_lag_phase_advance_pending', False):
                self._lag_request_phase_advance()
            return
        if rem is None:
            self.lblLagCountdownMain.setVisible(False)
            self._set_countdown_label(self.lblLagCountdownMain, '')
            return
        self.lblLagCountdownMain.setVisible(True)
        self._set_countdown_label(
            self.lblLagCountdownMain, self._lag_countdown_label(allow, rem)
        )
        dlg = getattr(self, 'lag_switch_dialog', None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg.set_lag_countdown(rem, allow)
            except Exception:
                pass


    def _lag_phase_begin_block(self, device) -> None:
        if not self.lag_active or not isinstance(device, dict):
            return
        self._lag_phase_arming = False
        self._lag_bump_phase_seq()
        self._lag_in_allow_phase = False
        self._sync_lag_timing_values_from_ui()
        block_ms = max(1, int(self.lag_block_ms))
        self._lag_schedule_phase(block_ms)
        self._arm_lag_phase_countdown()
        cur = self._lag_resolved_victim() or device
        try:
            self._lag_apply_block(cur)
        except Exception:
            pass
        mac = str(cur.get('mac') or '').strip()
        if mac:
            self._refresh_table_row_for_mac(mac, cur.get('ip'))


    def _lag_phase_begin_allow(self, device) -> None:
        if not self.lag_active or not isinstance(device, dict):
            return
        self._cancel_lag_block_reassert()
        self._lag_bump_phase_seq()
        self._lag_in_allow_phase = True
        self._sync_lag_timing_values_from_ui()
        allow_ms = max(1, int(self.lag_release_ms))
        self._lag_schedule_phase(allow_ms)
        self._arm_lag_phase_countdown()
        cur = self._lag_resolved_victim() or device
        self._lag_apply_allow_phase_sync(cur)
        try:
            self._lag_ics_set_paused(cur, False)
        except Exception:
            pass
        self._lag_ics_force_unpause()
        mac = str(cur.get('mac') or '').strip()
        if mac:
            self._refresh_table_row_for_mac(mac, cur.get('ip'))


    def stopLagSwitch(self, refresh_dialog=True):
        if not self.lag_active:
            self._ics_teardown_gate_if_idle()
            return
        prev_mac = self.lag_device_mac
        snap = getattr(self, '_lag_device_snapshot', None)
        self._lag_restoring_after_stop = True
        gate = getattr(self, '_impairment', None)
        if gate is not None:
            gate.teardown.begin('lag', prev_mac)
        # Stop phase timer before clearing lag_active so a tick cannot re-block.
        self._lag_phase_end_timer.stop()
        self._lag_phase_advance_pending = False
        self._stop_lag_countdown()
        self._cancel_lag_block_reassert()
        device = self._lag_resolved_victim()

        # Instant resume (same path as Kill/Dupe OFF) — do not defer with QTimer.singleShot.
        if device:
            try:
                plan = self._impairment_plan_for(device)
                if plan.is_ics_downstream:
                    self._ics_emergency_release(device, heal=True)
                else:
                    self._lag_ics_set_paused(device, False)
                    self._clear_ics_client_block(device, pause_only=True)
                    ip = (device.get('ip') or '').strip()
                    if ip and _is_valid_ip(ip):
                        _bg_unblock_ip(ip)
                    # The previous "not in self.killer.killed" guard was inverted: lag
                    # ON paths call killer.kill() which adds the mac to killer.killed,
                    # so this branch skipped unkill exactly when it was needed and the
                    # ARP poison thread kept running after the UI showed OFF. Call
                    # unkill unconditionally — it's a safe no-op if not actually killed,
                    # and the only path that stops the ARP worker thread.
                    victim = self._victim_record_for_mac(device.get('mac') or '') or device
                    if victim:
                        try:
                            self.killer.unkill(victim)
                        except Exception:
                            try:
                                from tools.zubcut_log import app_log

                                app_log('lag_unkill_failed', mac=str(prev_mac or ''), exc_info=True)
                            except Exception:
                                pass
                        try:
                            self.killer.reinforce_restore(victim)
                        except Exception:
                            try:
                                from tools.zubcut_log import app_log

                                app_log('lag_reinforce_failed', mac=str(prev_mac or ''), exc_info=True)
                            except Exception:
                                pass
            except Exception:
                self._lag_ics_force_unpause()
        else:
            self._ics_teardown_gate_if_idle(prev_mac)
        if device:
            try:
                self._release_victim_arp_mitm_stack(device)
            except Exception:
                try:
                    from tools.zubcut_log import app_log

                    app_log('lag_release_stack_failed', mac=str(prev_mac or ''), exc_info=True)
                except Exception:
                    pass
            try:
                self._schedule_cut_analysis_after_off(device, flow='Lag')
            except Exception:
                pass

        self.lag_active = False
        self.lag_device_mac = None
        self.lag_device_ip = None
        self._lag_net_prepared_mac = None
        self._lag_ics_preblocked = False
        self._lag_lan_preblocked = False
        self._lag_phase_arming = False
        self._lag_in_allow_phase = False
        self._lag_restoring_after_stop = False
        self._lag_restoring_mac = None
        gate = getattr(self, '_impairment', None)
        if gate is not None:
            gate.teardown.end('lag')
        self._ics_teardown_gate_if_idle(prev_mac)
        self._sync_killed_devices()
        self.btnLagSwitch.setText('Lag Switch')
        self.btnLagSwitch.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self.log('Lag switch OFF', UI_LOG_RESTORE_FG)
        if refresh_dialog:
            self._refresh_flow_toggle_ui()
        else:
            self._updateLagSwitchButtonState()
            self._updateKillButtonState()
        self._repaint_all_table_rows_for_hover()
        dlg_lag = getattr(self, 'lag_switch_dialog', None)
        if dlg_lag is not None and dlg_lag.isVisible():
            try:
                dlg_lag.refresh_toggle_state()
            except Exception:
                pass
