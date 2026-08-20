"""Percent Cut flow engine (extracted from MainWindow)."""
from __future__ import annotations

from PyQt5.QtCore import QTimer, QEventLoop
from PyQt5.QtWidgets import QApplication

from tools.clumsy_inline import (
    clumsy_ics_lag_can_use_windivert,
    clumsy_ics_resolve_victim_ip,
    clumsy_windivert_unavailable_reason,
)
from tools.pfctl import _is_valid_ip
from tools.utils_gui import get_settings, set_settings
from gui.impairment_shared import (
    UI_LOG_RESTORE_FG,
    UI_LOG_VICTIM_BLOCK_FG,
    _focus_widget_absorbs_letter_key,
)


class ImpairmentPctCutMixin:
    def _shortcut_global_pctcut(self):
        if not self._app_window_is_foreground():
            return
        if _focus_widget_absorbs_letter_key(QApplication.focusWidget()):
            return
        self.togglePercentCut('shortcut_key')


    def _percent_cut_ui_shows_on(self, mac: str | None = None, ip: str | None = None) -> bool:
        """True when Percent Cut is armed for the selected row (or any victim when no row given)."""
        if not self.percent_cut_active:
            return False
        stored_mac = str(self.percent_cut_device_mac or '').strip()
        stored_ip = str(getattr(self, 'percent_cut_device_ip', None) or '').strip()
        if not mac and not ip:
            return bool(stored_mac or stored_ip)
        if stored_mac and mac and stored_mac == str(mac).strip():
            return True
        if stored_ip and ip and stored_ip == str(ip).strip():
            return True
        # Selected row is not the active Percent Cut victim.
        return False


    def _updatePercentCutButtonState(self):
        pct = self._clamp_percent(self.spinPercentCutMain.value())
        key = getattr(self, '_shortcut_label_pctcut', 'K')
        dev = self._get_selected_device()
        mac = str(dev.get('mac') or '').strip() if dev else ''
        ip = str(dev.get('ip') or '').strip() if dev else ''
        on = self._percent_cut_ui_shows_on(mac, ip)
        if on:
            self.btnPercentCut.setText(f'■ CUT {pct}% (Press {key} to turn off)')
            self.btnPercentCut.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnPercentCut.setText(f'Percent Cut: {pct}%')
            self.btnPercentCut.setStyleSheet(self.BUTTON_NORMAL_STYLE)


    @staticmethod
    def _clamp_percent(value):
        try:
            return max(1, min(100, int(value)))
        except Exception:
            return 100


    def _percent_cut_value(self):
        try:
            return self._clamp_percent(get_settings('traffic_percent'))
        except Exception:
            return 50


    def _on_percent_cut_value_changed(self, value):
        pct = self._clamp_percent(value)
        try:
            set_settings('traffic_percent', int(pct))
        except Exception:
            pass
        if self.percent_cut_active and self.percent_cut_device_mac:
            dev = self._get_device_by_mac(
                self.percent_cut_device_mac, getattr(self, 'percent_cut_device_ip', None)
            ) or self._victim_record_for_mac(self.percent_cut_device_mac)
            if dev:
                try:
                    if self._uses_windivert(dev):
                        dev = self._prepare_victim_for_impairment(dict(dev), fast=True)
                        self._ics_apply_percent_cut_windivert(dev, pct)
                    else:
                        allow_pct = max(0, 100 - pct)
                        dev = self._prepare_victim_for_impairment(dict(dev), fast=True)
                        self._refresh_victim_mac_from_system_arp(dev)
                        self.percent_cut_device_mac = dev.get('mac')
                        if not self.killer.apply_percent_cut(dev, pass_percent=allow_pct):
                            self.log('Percent Cut update failed — rescan target', 'red')
                except Exception:
                    pass
        self._updatePercentCutButtonState()


    def _percent_cut_forwarder_live(self, mac: str | None, ip: str | None = None) -> bool:
        """True when a Percent Cut forwarder is still running for this victim."""
        mac = str(mac or '').strip()
        ip = str(ip or '').strip()
        if mac and mac in getattr(self.killer, 'forwarders', {}):
            fw = self.killer.forwarders.get(mac)
            if fw is not None and getattr(fw, 'running', False):
                return True
        if ip:
            for victim in (self.killer.killed or {}).values():
                if not isinstance(victim, dict):
                    continue
                if str(victim.get('ip') or '').strip() != ip:
                    continue
                vm = str(victim.get('mac') or '').strip()
                if vm and vm in getattr(self.killer, 'forwarders', {}):
                    fw = self.killer.forwarders.get(vm)
                    if fw is not None and getattr(fw, 'running', False):
                        return True
        return False


    def _percent_cut_backend_active(self, mac: str | None, ip: str | None = None) -> bool:
        """True when Percent Cut UI is on and the forwarder still shapes this victim."""
        if not getattr(self, 'percent_cut_active', False):
            return False
        return self._percent_cut_forwarder_live(mac, ip)


    def _resolve_pctcut_stop_snapshot(self, prev_mac, prev_ip):
        """Victim for Percent Cut OFF (MAC may have been refreshed while ON)."""
        return self._resolve_dupe_stop_snapshot(prev_mac, prev_ip, None)


    def _pctcut_start_cancelled(self, pct_gen: int) -> bool:
        """True when OFF cancelled this deferred ON (gen bump and/or active cleared)."""
        return (
            not getattr(self, 'percent_cut_active', False)
            or int(getattr(self, '_pctcut_start_gen', 0)) != int(pct_gen)
        )

    def _pctcut_undo_cancelled_arm(self, device) -> None:
        """If deferred ON applied after OFF, tear the cut back down immediately."""
        if not isinstance(device, dict):
            return
        mac = str(device.get('mac') or '').strip()
        ip = str(device.get('ip') or '').strip()
        try:
            self._pctcut_instant_resume(mac, ip)
        except Exception:
            pass

    def togglePercentCut(self, source='unknown'):
        if not self.connected():
            return
        device = self._get_selected_device()
        if not device:
            self.log('No device selected', 'red')
            return
        if device['admin']:
            self.log('Cannot cut admin device', UI_LOG_VICTIM_BLOCK_FG)
            return

        # Paint from the selected row first — resolve_live_lan_victim (ping) runs
        # in deferred start so the button is not stuck waiting on ARP/resolve.
        device = dict(device)
        mac = str(device.get('mac') or '').strip()
        ip = str(device.get('ip') or '').strip()
        if not _is_valid_ip(ip):
            self.log('Target has no IP yet — cannot percent cut.', 'red')
            return
        if not mac:
            self.log('Target has no MAC yet — rescan after PS5 Wi‑Fi/Ethernet change.', 'red')
            return
        if self._percent_cut_ui_shows_on(mac, ip):
            if self._ignore_duplicate_toggle_edge('pctcut', mac, 'stop'):
                return
            self.stopPercentCut(log=True)
            return
        # UI already OFF but MITM/forwarder residue still cutting — force restore
        # (second OFF click used to re-arm ON and leave the victim stuck).
        if not self.percent_cut_active and (
            self._percent_cut_forwarder_live(mac, ip)
            or (
                mac in getattr(self.killer, 'killed', {})
                and not self._killed_profile_on(device)
                and not self.lag_active
                and not self.dupe_active
                and not getattr(self, 'mitm_shaping_active', False)
            )
        ):
            if self._ignore_duplicate_toggle_edge('pctcut', mac, 'stop'):
                return
            if not self.percent_cut_device_mac:
                self.percent_cut_device_mac = mac
            if not getattr(self, 'percent_cut_device_ip', None):
                self.percent_cut_device_ip = ip
            self.stopPercentCut(log=True)
            return
        # Block bounce-back ON right after OFF (pressed-signal / deferred re-entry).
        try:
            import time as _time

            if _time.monotonic() < float(getattr(self, '_pctcut_off_until', 0.0) or 0.0):
                return
        except Exception:
            pass
        if self._toggle_start_blocked('pctcut'):
            return
        if self._ignore_duplicate_toggle_edge('pctcut', mac, 'start'):
            return

        had_prior_pct_other_mac = bool(
            self.percent_cut_active
            and self.percent_cut_device_mac
            and self.percent_cut_device_mac != mac
        )
        prior_pct_mac = str(self.percent_cut_device_mac or '').strip() if had_prior_pct_other_mac else ''
        prior_pct_ip = (
            str(getattr(self, 'percent_cut_device_ip', None) or '').strip()
            if had_prior_pct_other_mac
            else ''
        )
        pct = self._clamp_percent(self.spinPercentCutMain.value())
        allow_pct = max(0, 100 - pct)
        self.percent_cut_active = True
        self.percent_cut_device_mac = mac
        self.percent_cut_device_ip = ip
        self.btnPercentCut.setText(f'■ CUT {pct}%')
        self.btnPercentCut.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        self._paint_flow_start_ui('pctcut', device)
        try:
            app = QApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.ExcludeUserInputEvents)
        except Exception:
            pass

        # Cut traffic on this click (Lag/Kill/Dupe instant-preblock parity).
        self._pctcut_preapplied = False
        try:
            self._begin_cut_analysis_session(dict(device), flow='Percent Cut', cut_pct=pct)
        except Exception:
            pass
        try:
            self._pctcut_instant_apply(dict(device), pct)
        except Exception:
            self._pctcut_preapplied = False

        self._pctcut_start_gen = int(getattr(self, '_pctcut_start_gen', 0)) + 1
        pct_gen = self._pctcut_start_gen
        pct_device = dict(device)
        pct_val = pct
        pct_allow = allow_pct
        pct_preapplied = bool(getattr(self, '_pctcut_preapplied', False))

        def _pctcut_deferred_start():
            if getattr(self, '_shutting_down', False):
                return
            if self._pctcut_start_cancelled(pct_gen):
                return
            armed_device = dict(pct_device)
            try:
                device = self._resolve_flow_start_device(dict(pct_device))
                if self._pctcut_start_cancelled(pct_gen):
                    return
                mac = str(device.get('mac') or '').strip()
                ip = str(device.get('ip') or '').strip()
                if mac:
                    self.percent_cut_device_mac = mac
                if ip:
                    self.percent_cut_device_ip = ip
                armed_device = dict(device)
                if had_prior_pct_other_mac and prior_pct_mac:
                    prior = self._resolve_pctcut_stop_snapshot(prior_pct_mac, prior_pct_ip)
                    if prior:
                        try:
                            self._release_pctcut_victim_immediate(prior)
                        except Exception:
                            pass
                if self.mitm_shaping_active:
                    # Do not await teardown on the GUI thread (Lag deferred parity).
                    self.stop_mitm_shaping(log=False)
                if self.lag_active and self.lag_device_mac == mac:
                    self.stopLagSwitch(refresh_dialog=True)
                if self.dupe_active and self.dupe_device_mac == mac:
                    self.stopDupe(log=False)
                    self._flush_pending_dupe_clear_sync(max_wait_ms=200)
                if self._kill_ui_shows_on(mac, device.get('ip'), device):
                    self._clear_explicit_kill_for_flow(dict(device))
                if self._pctcut_start_cancelled(pct_gen):
                    return
                pct = pct_val
                allow_pct = pct_allow
                plan = self._impairment_plan_for(device)
                # Use the click-time latch only. OFF clears self._pctcut_preapplied;
                # ANDing with that forced a full re-apply after quick OFF stopped the
                # forwarder (Lag uses lan_preblocked the same way — never re-kill).
                click_preapplied = bool(pct_preapplied)
                if plan.is_ics_downstream:
                    if not clumsy_ics_lag_can_use_windivert(device, self.scanner):
                        self.percent_cut_active = False
                        self.percent_cut_device_mac = None
                        self.percent_cut_device_ip = None
                        self._pctcut_preapplied = False
                        self.log(
                            'Percent Cut on hotspot needs WinDivert: '
                            + clumsy_windivert_unavailable_reason(device),
                            'red',
                        )
                        self._refresh_flow_toggle_ui()
                        return
                    if click_preapplied and self._ics_stack_is_warm():
                        if self._pctcut_start_cancelled(pct_gen):
                            return
                        rip = self._ics_hotspot_victim_ip(device, pctcut=True) or str(
                            device.get('ip') or ''
                        ).strip()
                        if rip:
                            device['ip'] = rip
                        # Refresh cut ratio for resolved IP only while still ON.
                        if self._pctcut_start_cancelled(pct_gen):
                            return
                        if not self._ics_apply_percent_cut_windivert(device, pct):
                            click_preapplied = False
                        if self._pctcut_start_cancelled(pct_gen):
                            self._pctcut_undo_cancelled_arm(device)
                            return
                    if not click_preapplied:
                        if self._pctcut_start_cancelled(pct_gen):
                            return
                        device = self._prepare_victim_for_impairment(dict(device), fast=True)
                        if self._pctcut_start_cancelled(pct_gen):
                            return
                        if not self._ics_apply_percent_cut_windivert(device, pct):
                            self.percent_cut_active = False
                            self.percent_cut_device_mac = None
                            self.percent_cut_device_ip = None
                            self._pctcut_preapplied = False
                            self.log(
                                'Percent Cut needs WinDivert (run as Administrator).',
                                'red',
                            )
                            self._refresh_flow_toggle_ui()
                            return
                        if self._pctcut_start_cancelled(pct_gen):
                            self._pctcut_undo_cancelled_arm(device)
                            return
                    resolved_ip = self._ics_hotspot_victim_ip(device, pctcut=True)
                else:
                    if click_preapplied and self._lan_mitm_stack_is_warm():
                        # Lag lan_preblocked parity: refresh MAC / reassert only —
                        # never apply_percent_cut (kill+forwarder) after quick OFF
                        # cleared the forwarder, which re-armed the cut behind OFF UI.
                        if self._pctcut_start_cancelled(pct_gen):
                            return
                        self._refresh_victim_mac_from_system_arp(device)
                        mac = str(device.get('mac') or '').strip()
                        if self._pctcut_start_cancelled(pct_gen):
                            return
                        if mac:
                            self.percent_cut_device_mac = mac
                        if self._percent_cut_forwarder_live(mac, device.get('ip')):
                            try:
                                self.killer.reassert_poison(device)
                            except Exception:
                                pass
                        else:
                            # Still ON but forwarder died — re-arm only if OFF did not win.
                            if self._pctcut_start_cancelled(pct_gen):
                                return
                            if not self.killer.apply_percent_cut(
                                device, pass_percent=allow_pct
                            ):
                                click_preapplied = False
                            if self._pctcut_start_cancelled(pct_gen):
                                self._pctcut_undo_cancelled_arm(device)
                                return
                    if not click_preapplied:
                        if self._pctcut_start_cancelled(pct_gen):
                            return
                        device = self._prepare_victim_for_impairment(dict(device), fast=True)
                        self._refresh_victim_mac_from_system_arp(device)
                        mac = str(device.get('mac') or '').strip()
                        if self._pctcut_start_cancelled(pct_gen):
                            return
                        if mac:
                            self.percent_cut_device_mac = mac
                        if self._pctcut_start_cancelled(pct_gen):
                            return
                        if not self.killer.apply_percent_cut(device, pass_percent=allow_pct):
                            self.percent_cut_active = False
                            self.percent_cut_device_mac = None
                            self.percent_cut_device_ip = None
                            self._pctcut_preapplied = False
                            try:
                                self._release_pctcut_victim_immediate(device)
                            except Exception:
                                pass
                            self.log(
                                'Percent Cut failed — router MAC or adapter missing (rescan, ping PS5)',
                                'red',
                            )
                            self._refresh_flow_toggle_ui()
                            return
                        if self._pctcut_start_cancelled(pct_gen):
                            self._pctcut_undo_cancelled_arm(device)
                            return
                    if self._pctcut_start_cancelled(pct_gen):
                        return
                    self._log_mitm_arm_status(device, action='Percent Cut')
                    resolved_ip = clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
                        device.get('ip') or ''
                    ).strip()
                if self._pctcut_start_cancelled(pct_gen):
                    self._pctcut_undo_cancelled_arm(device)
                    return
                armed_device = dict(device)
                self.percent_cut_device_ip = resolved_ip
                self._pctcut_preapplied = True
                self.log(
                    f'Percent Cut ON for {resolved_ip or ip}: {pct}% cut ({allow_pct}% pass)',
                    UI_LOG_VICTIM_BLOCK_FG,
                )
                self._schedule_cut_analysis_if_enabled(
                    device, flow='Percent Cut', cut_pct=pct
                )
                self._refresh_flow_toggle_ui()
            except Exception as exc:
                if self._pctcut_start_cancelled(pct_gen):
                    self._pctcut_undo_cancelled_arm(armed_device)
                    return
                self.percent_cut_active = False
                self.percent_cut_device_mac = None
                self.percent_cut_device_ip = None
                self._pctcut_preapplied = False
                self._refresh_flow_toggle_ui()
                self.log(f'Percent Cut failed to start: {exc}', 'red')

        QTimer.singleShot(0, _pctcut_deferred_start)


    def stopPercentCut(self, log=True):
        """Paint OFF first (Dupe parity), then unkill/release MITM on this stack."""
        if not self.percent_cut_active:
            # Scan / Kill All always call this. Do not unpause the shared WinDivert
            # gate that hotspot Kill still owns.
            return
        prev_mac = self.percent_cut_device_mac
        prev_ip = getattr(self, 'percent_cut_device_ip', None)
        was_ui_on = bool(self.percent_cut_active)
        # Cancel any in-flight deferred ON so it cannot re-arm after this OFF.
        self._pctcut_start_gen = int(getattr(self, '_pctcut_start_gen', 0)) + 1
        self.percent_cut_active = False
        self.percent_cut_device_mac = None
        self.percent_cut_device_ip = None
        self._pctcut_preapplied = False
        try:
            import time as _time

            # Prevent pressed/deferred bounce from turning CUT back on immediately.
            self._pctcut_off_until = _time.monotonic() + 0.4
        except Exception:
            self._pctcut_off_until = 0.0

        # Snapshot before resume pops killer.killed (needed for reinforce/log).
        snap_mac = str(prev_mac or '').strip()
        snap_ip = str(prev_ip or '').strip()
        snap = None
        if snap_mac or snap_ip:
            snap = self._victim_record_for_mac(snap_mac) if snap_mac else None
            if not isinstance(snap, dict) and snap_ip:
                for entry in list((self.killer.killed or {}).values()):
                    if isinstance(entry, dict) and str(entry.get('ip') or '').strip() == snap_ip:
                        snap = dict(entry)
                        snap_mac = str(snap.get('mac') or snap_mac).strip()
                        break
            if not isinstance(snap, dict):
                snap = {'mac': snap_mac or '', 'ip': snap_ip or ''}
            else:
                snap = dict(snap)
                if snap_ip and not str(snap.get('ip') or '').strip():
                    snap['ip'] = snap_ip

        # Direct chrome like Dupe — paint before network work so OFF never feels stuck.
        pct = self._clamp_percent(self.spinPercentCutMain.value())
        self.btnPercentCut.setText(f'Percent Cut: {pct}%')
        self.btnPercentCut.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        try:
            self._flush_gui_events()
        except Exception:
            try:
                app = QApplication.instance()
                if app is not None:
                    app.processEvents(QEventLoop.ExcludeUserInputEvents)
            except Exception:
                pass

        # Connectivity now: pass_all + unkill only (Lag click parity). Heavy
        # reinforce/stack sweep runs in _finish_off so OFF is not a 3–5s stall.
        try:
            self._pctcut_instant_resume(snap_mac or prev_mac, snap_ip or prev_ip)
        except Exception:
            pass
        try:
            if isinstance(snap, dict):
                self._schedule_cut_analysis_after_off(snap, flow='Percent Cut')
        except Exception:
            pass

        # Re-assert OFF chrome after resume (resume must not leave ON styling).
        self.btnPercentCut.setText(f'Percent Cut: {pct}%')
        self.btnPercentCut.setStyleSheet(self.BUTTON_NORMAL_STYLE)

        want_log = bool(log)
        showed_on = was_ui_on

        def _finish_off():
            # Keep OFF latch alive across reinforce callbacks.
            try:
                import time as _time

                self._pctcut_off_until = max(
                    float(getattr(self, '_pctcut_off_until', 0.0) or 0.0),
                    _time.monotonic() + 0.25,
                )
            except Exception:
                pass
            if snap_mac and isinstance(snap, dict):
                try:
                    self._pctcut_off_reinforce_now(snap_mac, snap)
                except Exception:
                    pass
                try:
                    self._schedule_pctcut_off_reinforce(snap_mac, snap)
                except Exception:
                    pass
                try:
                    QTimer.singleShot(
                        150, lambda m=snap_mac: self._ics_teardown_gate_if_idle(m)
                    )
                except Exception:
                    pass
            if want_log:
                if snap_ip or (isinstance(snap, dict) and snap.get('ip')):
                    ip = str((snap or {}).get('ip') or snap_ip or '')
                    self.log('Percent Cut OFF for ' + ip, UI_LOG_RESTORE_FG)
                elif showed_on:
                    self.log('Percent Cut OFF', UI_LOG_RESTORE_FG)
            try:
                self._refresh_flow_toggle_ui(fast=True)
            except Exception:
                pass
            if isinstance(snap, dict):
                try:
                    mac = str(snap.get('mac') or snap_mac or '').strip()
                    if mac:
                        self._refresh_table_row_for_mac(mac, snap.get('ip') or snap_ip)
                except Exception:
                    pass

        QTimer.singleShot(0, _finish_off)
