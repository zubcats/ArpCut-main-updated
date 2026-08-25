"""Dupe flow engine (extracted from MainWindow)."""
from __future__ import annotations

import time
from functools import partial

from PyQt5.QtCore import Qt, QMetaObject, QTimer, pyqtSlot, QEventLoop
from PyQt5.QtWidgets import QApplication

from tools.pfctl import _is_valid_ip
from gui.impairment_shared import (
    UI_LOG_RESTORE_FG,
    UI_LOG_VICTIM_BLOCK_FG,
    _dupe_net_run_unblock,
    _focus_widget_absorbs_letter_key,
    format_countdown_ms,
)


class ImpairmentDupeMixin:
    def _show_dupe_status(self, text, color=UI_LOG_VICTIM_BLOCK_FG, *, hold_ms=8000):
        """Dupe feedback on the status strip; countdown label stays for the timer."""
        plain = str(text or '').strip()
        if not plain:
            return
        self.log(plain, color)
        if not self.dupe_active:
            self.lblDupeCountdownMain.setVisible(True)
            self._set_countdown_label(self.lblDupeCountdownMain, plain)
            if hold_ms > 0:
                QTimer.singleShot(hold_ms, self._clear_dupe_status_label_if_idle)


    def _clear_dupe_status_label_if_idle(self):
        if self.dupe_active:
            return
        self.lblDupeCountdownMain.setVisible(False)
        self.lblDupeCountdownMain.setText('')


    def _dupe_cut_still_active(self, mac: str, ip: str) -> bool:
        """True when ARP MITM or a hard-drop forwarder still owns this victim."""
        killer = getattr(self, 'killer', None)
        if killer is None:
            return False
        killed = getattr(killer, 'killed', {}) or {}
        if mac and mac in killed:
            return True
        if ip:
            for entry in list(killed.values()):
                if isinstance(entry, dict) and str(entry.get('ip') or '').strip() == ip:
                    return True

        def _is_hard_cut(fw) -> bool:
            if fw is None or not getattr(fw, 'running', False):
                return False
            try:
                if bool(getattr(fw, 'drop_from_victim', False)):
                    return True
                return int(getattr(fw, 'pass_from_victim_pct', 100) or 100) <= 0
            except Exception:
                return True

        fws = getattr(killer, 'forwarders', {}) or {}
        if mac and _is_hard_cut(fws.get(mac)):
            return True
        if ip:
            for fmac, fw in list(fws.items()):
                victim = killed.get(fmac) or {}
                vip = str((victim or {}).get('ip') or '').strip()
                if vip == ip and _is_hard_cut(fw):
                    return True
        return False

    def _log_dupe_restore_result(self, device) -> None:
        """After Dupe OFF, report whether MITM/forwarder actually cleared."""
        if not isinstance(device, dict):
            self._show_dupe_status('Dupe OFF', UI_LOG_RESTORE_FG)
            return
        ip = str(device.get('ip') or '').strip()
        mac = str(device.get('mac') or '').strip()
        still = self._dupe_cut_still_active(mac, ip)
        if still:
            self._show_dupe_status(
                f'Dupe OFF: cut still active on {ip} — press Dupe or Kill OFF, then rescan',
                'red',
                hold_ms=12000,
            )
            return
        if mac:
            self._show_dupe_status(
                f'Dupe OFF: restored {ip} ({mac})',
                UI_LOG_RESTORE_FG,
                hold_ms=10000,
            )
        else:
            self._show_dupe_status(f'Dupe OFF: restored {ip}', UI_LOG_RESTORE_FG, hold_ms=10000)
    

    def _shortcut_global_dupe(self, *, from_button: bool = False):
        """Dupe toggle while app is foreground, regardless of active sub-window."""
        if not from_button:
            if not self._app_window_is_foreground():
                return
            if _focus_widget_absorbs_letter_key(QApplication.focusWidget()):
                return
        if self.dupe_active and self.dupe_device_mac:
            dupe_edge = 'stop'
            if self._ignore_duplicate_toggle_edge('dupe', self.dupe_device_mac, dupe_edge):
                return
            self.stopDupe()
            return
        device = self._get_selected_device()
        if device is None:
            self.log('No device selected', 'red')
            return
        if device['admin']:
            self.log('Cannot dupe admin device', UI_LOG_VICTIM_BLOCK_FG)
            return
        if self._toggle_start_blocked('dupe', device):
            return
        dupe_edge = 'start'
        if self._ignore_duplicate_toggle_edge('dupe', device['mac'], dupe_edge):
            return
        ms, direction = self._dupe_inline_values()
        self.dupe_duration_ms = ms
        self.dupe_direction = direction
        self.startDupe(device, self.dupe_duration_ms, self.dupe_direction)


    def _dupe_inline_values(self):
        return self.dupeSpinMain.value(), self._direction_from_checks(
            self.dupeDirBoth, self.dupeDirIncoming, self.dupeDirOutgoing
        )


    def _finish_dupe_ics_teardown_net(self, device) -> bool:
        if not isinstance(device, dict):
            return False
        plan = self._impairment_plan_for(device)
        if not plan.is_ics_downstream:
            return False
        self._ics_emergency_release(device, heal=True)
        return True


    def _finish_dupe_ics_teardown_ui(self, device) -> None:
        mac = str(device.get('mac') or '').strip() if isinstance(device, dict) else ''
        self._sync_killed_devices()
        if mac:
            self._refresh_table_row_for_mac(mac, device.get('ip'))
        self._updateKillButtonState()
        self._drop_dupe_restoring_banner()


    def _finish_dupe_ics_teardown(self, device, prev_mac: str | None) -> bool:
        """Fast dupe OFF on hotspot: WinDivert + any stray ARP/firewall, then heal gateway."""
        del prev_mac
        if not self._finish_dupe_ics_teardown_net(device):
            return False
        self._finish_dupe_ics_teardown_ui(device)
        return True


    def _sync_dupe_device_identity(self, device) -> None:
        """Keep dupe_device_mac/ip aligned after ARP refresh (killer may rekey MAC)."""
        if not isinstance(device, dict):
            return
        mac = str(device.get('mac') or '').strip()
        ip = str(device.get('ip') or '').strip()
        if mac:
            self.dupe_device_mac = mac
        if ip:
            self.dupe_device_ip = ip


    def _resolve_dupe_stop_snapshot(self, prev_mac, prev_ip, arm_snap):
        """Victim dict for dupe OFF — match by IP/MAC even when ARP rekeyed mid-burst."""
        ip = str(prev_ip or '').strip()
        mac = str(prev_mac or '').strip()
        live = self._get_device_by_mac(mac, ip) if mac or ip else None
        if not live and ip:
            for row in self.scanner.devices:
                if str(row.get('ip') or '').strip() == ip:
                    live = row
                    break
        for victim in (self.killer.killed or {}).values():
            if not isinstance(victim, dict):
                continue
            v_ip = str(victim.get('ip') or '').strip()
            v_mac = str(victim.get('mac') or '').strip()
            if ip and v_ip == ip:
                return dict(victim)
            if mac and v_mac == mac:
                return dict(victim)
        if isinstance(arm_snap, dict):
            if ip and str(arm_snap.get('ip') or '').strip() == ip:
                snap = dict(arm_snap)
            elif mac and str(arm_snap.get('mac') or '').strip() == mac:
                snap = dict(arm_snap)
            else:
                snap = None
            if snap:
                if live:
                    if not str(snap.get('ip') or '').strip():
                        snap['ip'] = live.get('ip')
                    if not str(snap.get('mac') or '').strip():
                        snap['mac'] = live.get('mac')
                return snap
        if live:
            return dict(live)
        return None


    def _drain_dupe_async_network(self, max_wait_ms: int = 400):
        """Wait for in-flight async unblock_ip; Queued unkill slot must run on the GUI thread."""
        cap = max(50, int(max_wait_ms))
        fut = getattr(self, '_dupe_clear_future', None)
        if fut is not None:
            self._pump_gui_until(lambda: fut.done(), cap)
            try:
                if fut.done():
                    fut.result(timeout=0)
            except Exception:
                pass
            self._dupe_clear_future = None
        self._pump_gui_until(
            lambda: getattr(self, '_dupe_async_unblock_ctx', None) is None,
            cap,
        )
        ctx = getattr(self, '_dupe_async_unblock_ctx', None)
        if ctx:
            device, prev_mac = ctx
            self._dupe_async_unblock_ctx = None
            try:
                if device and device.get('mac') == prev_mac:
                    self._release_dupe_victim_immediate(device)
            except Exception:
                pass
            self._sync_killed_devices()
            self._drop_dupe_restoring_banner()


    def _drain_dupe_block_if_needed(self):
        """Wait for in-flight async block_ip and its main-thread completion slot."""
        fut = getattr(self, '_dupe_block_future', None)
        if fut is None and not getattr(self, '_dupe_block_apply_pending', False):
            return
        if fut is not None:
            self._pump_gui_until(lambda: fut.done(), 400)
            try:
                if fut.done():
                    fut.result(timeout=0)
            except Exception:
                pass
            self._dupe_block_future = None
        self._pump_gui_until(
            lambda: not getattr(self, '_dupe_block_apply_pending', False),
            2500,
        )
        self._dupe_block_apply_pending = False
        self._dupe_block_ctx = None


    def _drop_dupe_restoring_banner(self):
        """Clear 'Restoring network…' after dupe firewall/unkill teardown completes."""
        self._dupe_restoring_after_stop = False
        self._dupe_restoring_mac = None
        gate = getattr(self, '_impairment', None)
        if gate is not None:
            gate.teardown.end('dupe')
        self.lblDupeCountdownMain.setVisible(False)
        self.lblDupeCountdownMain.setText('')
        dlg = getattr(self, 'dupe_switch_dialog', None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg.refresh_toggle_state()
            except Exception:
                pass


    def _flush_pending_dupe_clear_sync(self, max_wait_ms: int = 400):
        """Run any scheduled dupe OFF firewall/ARP work immediately (before starting a new dupe)."""
        self._dupe_deferred_clear_timer.stop()
        try:
            self._dupe_deferred_clear_timer.timeout.disconnect()
        except TypeError:
            pass
        self._drain_dupe_async_network(max_wait_ms)
        self._drain_dupe_block_if_needed()
        pending = self._dupe_pending_clear
        self._dupe_pending_clear = None
        if not pending:
            return
        prev_mac, snap = pending[0], pending[1]
        prev_ip = str((snap or {}).get('ip') or getattr(self, '_dupe_restoring_ip', None) or '').strip()
        device = self._resolve_dupe_stop_snapshot(prev_mac, prev_ip, snap)
        if not device:
            self._sync_killed_devices()
            self._drop_dupe_restoring_banner()
            return
        try:
            self._release_dupe_victim_immediate(device)
        except Exception:
            pass
        self._sync_killed_devices()
        self._drop_dupe_restoring_banner()


    def _do_deferred_dupe_clear(self):
        """Background firewall cleanup only; ARP/WinDivert restore runs in stopDupe."""
        self._dupe_deferred_clear_timer.stop()
        try:
            self._dupe_deferred_clear_timer.timeout.disconnect()
        except TypeError:
            pass
        pending = self._dupe_pending_clear
        self._dupe_pending_clear = None
        if not pending:
            return
        prev_mac, snap = pending[0], pending[1]
        prev_ip = str((snap or {}).get('ip') or getattr(self, '_dupe_restoring_ip', None) or '').strip()
        device = self._resolve_dupe_stop_snapshot(prev_mac, prev_ip, snap)
        if not device:
            self._sync_killed_devices()
            self._drop_dupe_restoring_banner()
            return
        snap = dict(device)
        if self._uses_windivert(snap):
            try:
                self._finish_dupe_ics_teardown_net(snap)
            except Exception:
                pass
            self._finish_dupe_ics_teardown_ui(snap)
            self._drop_dupe_restoring_banner()
            return
        ip = (device.get('ip') or '').strip()
        ex = getattr(self, '_dupe_net_executor', None)
        if ex is None or not ip:
            self._sync_killed_devices()
            self._drop_dupe_restoring_banner()
            return
        self._dupe_async_unblock_ctx = (device, prev_mac)
        fut = ex.submit(_dupe_net_run_unblock, ip)
        self._dupe_clear_future = fut

        def _done(_f):
            QMetaObject.invokeMethod(self, '_slot_finish_async_dupe_unblock', Qt.QueuedConnection)

        fut.add_done_callback(_done)

    @pyqtSlot()
    def _slot_finish_async_dupe_unblock(self):
        ctx = getattr(self, '_dupe_async_unblock_ctx', None)
        self._dupe_async_unblock_ctx = None
        self._dupe_clear_future = None
        if not ctx:
            self._drop_dupe_restoring_banner()
            return
        device, prev_mac = ctx
        if not device or device.get('mac') != prev_mac:
            self._sync_killed_devices()
            self._drop_dupe_restoring_banner()
            return
        try:
            if self._uses_windivert(device):
                self._finish_dupe_ics_teardown_ui(dict(device))
        except Exception:
            pass
        self._sync_killed_devices()
        if prev_mac:
            self._refresh_table_row_for_mac(prev_mac)
        self._updateKillButtonState()
        self._drop_dupe_restoring_banner()

    @pyqtSlot()
    def _slot_dupe_release_done(self):
        cb = getattr(self, '_dupe_release_done_cb', None)
        self._dupe_release_done_cb = None
        if cb is not None:
            try:
                cb()
            except Exception:
                pass


    def _arm_dupe_burst_wall_clock(self):
        """Wall-clock deadline + countdown from apply start so UI stays in sync while block_ip lags."""
        dur = max(1, int(self.dupe_duration_ms))
        self._dupe_end_mono = time.monotonic() + dur / 1000.0
        self._dupe_elapsed.start()
        self._dupe_countdown_timer.start()
        self._tick_dupe_countdown()


    def _abort_dupe_apply_failed(self):
        """Stop timers after failed dupe apply (after arm may have run)."""
        self._dupe_countdown_timer.stop()
        self.dupe_timer.stop()
        self._dupe_end_mono = None
        # D5: clear the queued countdown-finish flag so a late callback won't
        # re-enter the teardown after stopDupe already restored state. Only set
        # in _tick_dupe_countdown after a successful apply, but defensive here
        # since the apply path also reaches this on the dupe_duration_ms < apply
        # time edge case.
        self._dupe_finish_from_countdown_pending = False
        self.lblDupeCountdownMain.setVisible(False)
        self.lblDupeCountdownMain.setText('')


    def _abort_dupe_stuck_without_arm(self) -> None:
        """DUPE UI latched but deferred apply never received a victim snapshot."""
        self.dupe_active = False
        self.dupe_device_mac = None
        self.dupe_device_ip = None
        self._abort_dupe_apply_failed()
        self.btnDupe.setText('Dupe')
        self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self.log('Dupe failed to arm — try again', 'red')
        self._refresh_flow_toggle_ui()
        self._repaint_all_table_rows_for_hover()


    def _schedule_dupe_arm_command(self, device, direction: str, arm_gen: int) -> None:
        """Paint optimistic Dupe UI first; arm MITM on the next event-loop tick (Kill parity)."""
        dev = dict(device)
        QTimer.singleShot(
            0,
            lambda d=dev, dirn=str(direction), g=int(arm_gen): self._run_dupe_arm_command(
                d, dirn, g
            ),
        )


    def _run_dupe_arm_command(self, device, direction: str, arm_gen: int) -> None:
        """Arm Dupe MITM on the GUI thread — same stack as explicit Kill ON."""
        if getattr(self, '_shutting_down', False):
            return
        if not self.dupe_active or int(getattr(self, '_dupe_start_gen', 0)) != arm_gen:
            return
        mac_pin = str(getattr(self, 'dupe_device_mac', None) or '').strip()
        live = self._get_device_by_mac(mac_pin, getattr(self, 'dupe_device_ip', None))
        dev = dict(live) if isinstance(live, dict) else dict(device)
        dev = self._device_with_plan_ip(dev)
        if not self.dupe_active or int(getattr(self, '_dupe_start_gen', 0)) != arm_gen:
            return
        self.log(
            f'Dupe arming MITM → {dev.get("ip", "")} ({dev.get("mac", "")})…',
            UI_LOG_VICTIM_BLOCK_FG,
        )
        if self.lag_active:
            self.stopLagSwitch(refresh_dialog=True)
        if self.mitm_shaping_active:
            self.stop_mitm_shaping(log=False)
        if self.percent_cut_active:
            self.stopPercentCut(log=False)
        self._clear_explicit_kill_for_flow(dev)
        if not self.dupe_active or int(getattr(self, '_dupe_start_gen', 0)) != arm_gen:
            return
        block_dir = 'both'
        try:
            if getattr(self, '_dupe_preblocked', False):
                plan = self._impairment_plan_for(dev)
                if plan.use_windivert:
                    gate = getattr(self, '_ics_lag_gate', None)
                    if gate is None or not gate.is_running():
                        dev = self._prepare_victim_for_impairment(dev, fast=True)
                        if not self._apply_ics_client_block(dev, block_dir, for_dupe=True):
                            raise RuntimeError(
                                'Dupe block failed — rescan, pick Wi‑Fi in Settings if PC is on Wi‑Fi'
                            )
                else:
                    if (
                        not self.dupe_active
                        or int(getattr(self, '_dupe_start_gen', 0)) != arm_gen
                    ):
                        return
                    dev = dict(dev)
                    mac = str(dev.get('mac') or '').strip()
                    if mac:
                        try:
                            self.killer.reassert_poison(dev)
                        except Exception:
                            pass
                        try:
                            self.killer._apply_traffic_cut_sync(dev)
                        except Exception:
                            pass
                if self._dupe_impairment_is_live(dev):
                    self._dupe_armed_ok = True
                    dev = self._device_with_plan_ip(dict(dev))
                    self._sync_dupe_device_identity(dev)
                    self.dupe_device_mac = (
                        str(dev.get('mac') or self.dupe_device_mac or '').strip() or None
                    )
                    self.dupe_device_ip = dev.get('ip') or self.dupe_device_ip
                    # Instant cut already ran in preblock — seal after (Kill re-ON parity).
                    if not plan.use_windivert:
                        if (
                            not self.dupe_active
                            or int(getattr(self, '_dupe_start_gen', 0)) != arm_gen
                        ):
                            return
                        self._seal_lan_mitm_after_instant_cut(
                            dev, block_dir, action='Dupe'
                        )
                    self._start_dupe_timers_after_network_ready()
                    return
                self.log(
                    'Dupe preblock did not stick — arming full MITM…',
                    UI_LOG_VICTIM_BLOCK_FG,
                )
            if (
                not self.dupe_active
                or int(getattr(self, '_dupe_start_gen', 0)) != arm_gen
            ):
                return
            dev = self._prepare_victim_for_impairment(dev, fast=True)
            if not self._arm_victim_mitm_like_kill(dev, block_dir, flow='Dupe'):
                if (
                    not self.dupe_active
                    or int(getattr(self, '_dupe_start_gen', 0)) != arm_gen
                ):
                    return
                raise RuntimeError(
                    'Dupe block failed — rescan, pick Wi‑Fi in Settings if PC is on Wi‑Fi'
                )
            self._dupe_armed_ok = True
            dev = self._device_with_plan_ip(dict(dev))
            self._sync_dupe_device_identity(dev)
            self.dupe_device_mac = str(dev.get('mac') or self.dupe_device_mac or '').strip() or None
            self.dupe_device_ip = dev.get('ip') or self.dupe_device_ip
            self._start_dupe_timers_after_network_ready()
        except Exception as exc:
            self.dupe_active = False
            self.dupe_device_mac = None
            self.dupe_device_ip = None
            self._dupe_finish_from_countdown_pending = False
            self._dupe_block_apply_pending = False
            self._dupe_block_ctx = None
            self._dupe_block_future = None
            self._abort_dupe_apply_failed()
            self.btnDupe.setText('Dupe')
            self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
            try:
                if self._uses_windivert(dev):
                    self._ics_emergency_release(dev, heal=True)
                else:
                    self._clear_victim_block(dev)
            except Exception:
                pass
            self.log(f'Dupe failed to start: {exc}', 'red')
            self._refresh_flow_toggle_ui()
            self._repaint_all_table_rows_for_hover()


    def _apply_dupe_deferred(self):
        """Legacy entry — routed to _run_dupe_arm_command."""
        dev = getattr(self, '_dupe_arm_device', None)
        direction = getattr(self, '_dupe_arm_direction', 'both')
        gen = int(getattr(self, '_dupe_start_gen', 0))
        if not isinstance(dev, dict):
            if self.dupe_active:
                self._abort_dupe_stuck_without_arm()
            return
        self._run_dupe_arm_command(dev, direction, gen)

    @pyqtSlot()
    def _slot_finish_dupe_block(self):
        fut = getattr(self, '_dupe_block_future', None)
        self._dupe_block_future = None
        self._dupe_block_apply_pending = False
        ctx = getattr(self, '_dupe_block_ctx', None)
        self._dupe_block_ctx = None
        exc = None
        if fut is not None:
            try:
                exc = fut.result(timeout=0)
            except Exception as e:
                exc = e
        if not ctx:
            return
        dev, direction = ctx
        if exc is not None:
            self.dupe_active = False
            self.dupe_device_mac = None
            self.dupe_device_ip = None
            self._dupe_finish_from_countdown_pending = False
            self._abort_dupe_apply_failed()
            self.btnDupe.setText('Dupe')
            self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
            try:
                if self._uses_windivert(dev):
                    self._ics_emergency_release(dev, heal=True)
                else:
                    self._clear_victim_block(dev)
            except Exception:
                pass
            self.log(f'Dupe failed to start: {exc}', 'red')
            self._refresh_flow_toggle_ui()
            self._repaint_all_table_rows_for_hover()
            return
        if not self.dupe_active or self.dupe_device_mac != dev.get('mac'):
            return
        try:
            self._sync_killed_devices()
            self._refresh_table_row_for_mac(dev['mac'])
            self._updateKillButtonState()
            self._log_mitm_arm_status(dev, action='Dupe')
        except Exception:
            pass
        self._start_dupe_timers_after_network_ready()


    def _start_dupe_timers_after_network_ready(self):
        """
        Arm single-shot stop at remaining wall time. Countdown + _dupe_end_mono are already
        started in _arm_dupe_burst_wall_clock at apply begin so the timer matches ARP/block latency.
        """
        if getattr(self, '_dupe_end_mono', None) is None:
            self._arm_dupe_burst_wall_clock()
        rem_ms = max(0, int((self._dupe_end_mono - time.monotonic()) * 1000))
        if rem_ms <= 0:
            QTimer.singleShot(0, partial(self.stopDupe, True, True, 'Dupe finished'))
            return
        self.dupe_timer.start(rem_ms)
        self._tick_dupe_countdown()
        self._refresh_flow_toggle_ui()
        self._repaint_all_table_rows_for_hover()


    def startDupe(self, device, duration_ms, direction):
        device = self._resolve_flow_start_device(dict(device))
        if not _is_valid_ip(device.get('ip') or ''):
            self.log('Target has no IP yet — cannot start dupe.', 'red')
            return
        if self._toggle_start_blocked('dupe', device):
            return
        mac = str(device.get('mac') or '').strip()
        if not mac:
            self.log('Target has no MAC yet — rescan after PS5 Wi‑Fi/Ethernet change.', 'red')
            return
        had_prior_dupe = bool(self.dupe_active)
        if had_prior_dupe:
            prev_mac = self.dupe_device_mac
            prev_ip = getattr(self, 'dupe_device_ip', None)
            arm_snap = (
                dict(self._dupe_arm_device)
                if isinstance(getattr(self, '_dupe_arm_device', None), dict)
                else None
            )
            snap = self._resolve_dupe_stop_snapshot(prev_mac, prev_ip, arm_snap)
            if snap:
                try:
                    self._release_dupe_victim_immediate(snap, refresh_context=False)
                except Exception:
                    pass
            self._flush_pending_dupe_clear_sync(max_wait_ms=150)
            self._drop_dupe_restoring_banner()
        self._dupe_arm_timer.stop()
        try:
            self._dupe_arm_timer.timeout.disconnect()
        except TypeError:
            pass
        self.dupe_device_mac = mac
        self.dupe_device_ip = device.get('ip')
        self.dupe_direction = direction
        self.dupe_duration_ms = duration_ms
        self._dupe_armed_ok = False
        self.dupe_active = True
        self.btnDupe.setText('■ DUPE')
        self.btnDupe.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        self.lblDupeCountdownMain.setVisible(True)
        self._set_countdown_label(self.lblDupeCountdownMain, 'Arming…')
        dir_text = {'both': 'all', 'in': 'incoming', 'out': 'outgoing'}[direction]
        self._show_dupe_status(
            f'Dupe ON {duration_ms}ms ({dir_text}) → {device.get("ip")} — Dupe/P to stop early',
            UI_LOG_VICTIM_BLOCK_FG,
            hold_ms=0,
        )
        self._paint_flow_start_ui('dupe', device)
        self._arm_dupe_burst_wall_clock()
        self._dupe_countdown_timer.start()

        self._dupe_start_gen = int(getattr(self, '_dupe_start_gen', 0)) + 1
        dupe_gen = self._dupe_start_gen
        self._dupe_arm_device = dict(device)
        self._dupe_arm_direction = direction

        self._dupe_preblocked = False
        try:
            self._begin_cut_analysis_session(device, flow='Dupe')
        except Exception:
            pass
        try:
            self._flow_instant_preblock(device, direction, flow='Dupe')
        except Exception:
            pass

        def _dupe_deferred_start():
            if getattr(self, '_shutting_down', False):
                return
            if not self.dupe_active or int(getattr(self, '_dupe_start_gen', 0)) != dupe_gen:
                return
            self._schedule_dupe_arm_command(device, direction, dupe_gen)

        QTimer.singleShot(0, _dupe_deferred_start)

        def _dupe_arm_watchdog():
            if not self.dupe_active or int(getattr(self, '_dupe_start_gen', 0)) != dupe_gen:
                return
            if getattr(self, '_dupe_armed_ok', False):
                return
            live = self._get_device_by_mac(
                str(getattr(self, 'dupe_device_mac', None) or '').strip(),
                getattr(self, 'dupe_device_ip', None),
            ) or device
            self._run_dupe_arm_command(live, direction, dupe_gen)
            if getattr(self, '_dupe_armed_ok', False):
                return
            self.log(
                'Dupe arm did not start — retrying MITM (same path as Kill)…',
                'red',
            )
            self._schedule_dupe_arm_command(live, direction, dupe_gen)

        QTimer.singleShot(400, _dupe_arm_watchdog)


    def dupe_remaining_ms(self):
        if not self.dupe_active:
            return None
        end = getattr(self, '_dupe_end_mono', None)
        if end is None:
            return None
        return max(0, int((end - time.monotonic()) * 1000))


    def _tick_dupe_countdown(self):
        if not self.dupe_active:
            self._dupe_countdown_timer.stop()
            self.lblDupeCountdownMain.setVisible(False)
            self.lblDupeCountdownMain.setText('')
            return
        end = getattr(self, '_dupe_end_mono', None)
        if end is None:
            self.lblDupeCountdownMain.setVisible(True)
            self._set_countdown_label(self.lblDupeCountdownMain, 'Arming…')
            dlg = getattr(self, 'dupe_switch_dialog', None)
            if dlg is not None and dlg.isVisible():
                try:
                    dlg.set_dupe_countdown(None)
                except Exception:
                    pass
            return
        rem = self.dupe_remaining_ms()
        if rem is not None and rem <= 0:
            self.lblDupeCountdownMain.setVisible(True)
            self._set_countdown_label(self.lblDupeCountdownMain, 'Time left: 0.00s')
            self._dupe_finish_from_countdown('Dupe finished')
            return
        if rem is None or rem <= 0:
            self.lblDupeCountdownMain.setVisible(False)
            self._set_countdown_label(self.lblDupeCountdownMain, '')
        else:
            self.lblDupeCountdownMain.setVisible(True)
            self._set_countdown_label(self.lblDupeCountdownMain, format_countdown_ms(rem))
        dlg = getattr(self, 'dupe_switch_dialog', None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg.set_dupe_countdown(rem)
            except Exception:
                pass


    def _dupe_timer_fired(self):
        self._dupe_finish_from_countdown('Dupe finished')


    def _dupe_finish_from_countdown(self, log_message='Dupe finished'):
        if getattr(self, '_dupe_finish_from_countdown_pending', False):
            return
        self._dupe_finish_from_countdown_pending = True
        self._dupe_countdown_timer.stop()
        self._set_countdown_label(self.lblDupeCountdownMain, 'Time left: 0.00s')
        QTimer.singleShot(0, lambda: self._dupe_finish_from_countdown_sync(log_message))


    def _dupe_finish_from_countdown_sync(self, log_message='Dupe finished'):
        try:
            self.stopDupe(True, True, log_message)
        finally:
            self._dupe_finish_from_countdown_pending = False


    def stopDupe(self, refresh_dialog=True, log=True, log_message='Dupe stopped'):
        arm_snap = None
        if isinstance(getattr(self, '_dupe_arm_device', None), dict):
            arm_snap = dict(self._dupe_arm_device)
        self._dupe_arm_timer.stop()
        try:
            self._dupe_arm_timer.timeout.disconnect()
        except TypeError:
            pass
        self._dupe_arm_device = None
        was_active = self.dupe_active
        prev_mac = self.dupe_device_mac
        prev_ip = getattr(self, 'dupe_device_ip', None)
        self._dupe_countdown_timer.stop()
        self.dupe_timer.stop()
        self._dupe_end_mono = None
        self._dupe_finish_from_countdown_pending = False
        self._dupe_armed_ok = False
        if not was_active:
            self.lblDupeCountdownMain.setVisible(False)
            self.lblDupeCountdownMain.setText('')
            return
        self._dupe_restoring_after_stop = True
        self._dupe_restoring_mac = prev_mac
        self._dupe_restoring_ip = prev_ip
        gate = getattr(self, '_impairment', None)
        if gate is not None:
            gate.teardown.begin('dupe', prev_mac)
        self._show_dupe_status('Dupe OFF — restoring connection…', UI_LOG_RESTORE_FG, hold_ms=0)
        # Mark inactive after timers are stopped so _tick cannot race with teardown.
        # Bump gen so a late arm/watchdog cannot re-poison after UI shows OFF.
        self._dupe_start_gen = int(getattr(self, '_dupe_start_gen', 0)) + 1
        self.dupe_active = False
        self.dupe_device_mac = None
        self.dupe_device_ip = None
        self._dupe_preblocked = False
        self.btnDupe.setText('Dupe')
        self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        snap = self._resolve_dupe_stop_snapshot(prev_mac, prev_ip, arm_snap)
        self._refresh_flow_toggle_ui(fast=True)
        self._repaint_device_table_rows(snap)
        try:
            app = QApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.ExcludeUserInputEvents)
        except Exception:
            pass
        if snap:
            release_snap = dict(snap)
            release_mac = prev_mac
            # Sync restore on this stack (Lag OFF parity) — do not wait for the
            # next event-loop tick or poison can keep cutting after UI shows OFF.
            try:
                self._release_dupe_victim_immediate(release_snap, refresh_context=False)
            except Exception:
                try:
                    from tools.zubcut_log import app_log

                    app_log('dupe_release_failed', mac=str(release_mac or ''), exc_info=True)
                except Exception:
                    pass
            try:
                self._schedule_cut_analysis_after_off(release_snap, flow='Dupe')
            except Exception:
                pass
            try:
                self._sync_killed_devices()
                refresh_mac = str(release_snap.get('mac') or release_mac or '').strip()
                if refresh_mac:
                    self._refresh_table_row_for_mac(refresh_mac)
                self._updateKillButtonState()
                self._log_dupe_restore_result(release_snap)
            except Exception:
                pass
            # Clear teardown latch here — restore already finished. Waiting only on
            # deferred firewall cleanup left Dupe stuck on "still restoring".
            self._drop_dupe_restoring_banner()
            if refresh_dialog:
                self._refresh_flow_toggle_ui(fast=True)
            else:
                self._updateDupeButtonState()
                self._updateKillButtonState()
            self._repaint_device_table_rows(release_snap)
            dlg_dupe = getattr(self, 'dupe_switch_dialog', None)
            if dlg_dupe is not None and dlg_dupe.isVisible():
                try:
                    dlg_dupe.refresh_toggle_state()
                except Exception:
                    pass
            try:
                app = QApplication.instance()
                if app is not None:
                    app.processEvents(QEventLoop.ExcludeUserInputEvents)
            except Exception:
                pass
            # Do not drain in-flight block_ip here — restore must not wait on netsh add.
            self._dupe_block_apply_pending = False
            self._dupe_block_ctx = None
            self._dupe_block_future = None
            self._dupe_pending_clear = (prev_mac, snap)
            try:
                self._dupe_deferred_clear_timer.timeout.disconnect()
            except TypeError:
                pass
            # Must reconnect after disconnect — otherwise deferred clear never runs and
            # the teardown gate stays latched forever ("Dupe is still restoring").
            self._dupe_deferred_clear_timer.timeout.connect(
                self._do_deferred_dupe_clear, Qt.UniqueConnection
            )
            self._dupe_deferred_clear_timer.start(0)
            return
        elif prev_ip or prev_mac:
            try:
                for victim in list((self.killer.killed or {}).values()):
                    v_ip = str(victim.get('ip') or '').strip()
                    v_mac = str(victim.get('mac') or '').strip()
                    if (prev_ip and v_ip == str(prev_ip).strip()) or (
                        prev_mac and v_mac == str(prev_mac).strip()
                    ):
                        self._release_dupe_victim_immediate(victim)
                self._sync_killed_devices()
                self._updateKillButtonState()
            except Exception:
                pass
        if log:
            self._show_dupe_status(log_message, UI_LOG_RESTORE_FG)
        if refresh_dialog:
            self._refresh_flow_toggle_ui(fast=True)
        else:
            self._updateDupeButtonState()
            self._updateKillButtonState()
        self._repaint_device_table_rows(snap)
        dlg_dupe = getattr(self, 'dupe_switch_dialog', None)
        if dlg_dupe is not None and dlg_dupe.isVisible():
            try:
                dlg_dupe.refresh_toggle_state()
            except Exception:
                pass
        try:
            app = QApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.ExcludeUserInputEvents)
        except Exception:
            pass
        # Do not drain in-flight block_ip here — restore must not wait on netsh add.
        self._dupe_block_apply_pending = False
        self._dupe_block_ctx = None
        self._dupe_block_future = None
        self._dupe_pending_clear = (prev_mac, snap)
        try:
            self._dupe_deferred_clear_timer.timeout.disconnect()
        except TypeError:
            pass
        self._dupe_deferred_clear_timer.timeout.connect(self._do_deferred_dupe_clear, Qt.UniqueConnection)
        self._dupe_deferred_clear_timer.start(0)


    def _updateDupeButtonState(self):
        if self.dupe_active and self.dupe_device_mac:
            key = getattr(self, '_shortcut_label_dupe', 'P')
            self.btnDupe.setText(f'■ DUPE (Press {key} to turn off)')
            self.btnDupe.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnDupe.setText('Dupe')
            self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self._sync_inline_flow_controls_enabled()
