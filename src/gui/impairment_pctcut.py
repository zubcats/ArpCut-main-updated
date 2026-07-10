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

        device = self._resolve_flow_start_device(dict(device))
        mac = str(device.get('mac') or '').strip()
        ip = str(device.get('ip') or '').strip()
        if not _is_valid_ip(ip):
            self.log('Target has no IP yet — cannot percent cut.', 'red')
            return
        if not mac:
            self.log('Target has no MAC yet — rescan after PS5 Wi‑Fi/Ethernet change.', 'red')
            return
        if self._percent_cut_ui_shows_on(mac, ip):
            self.stopPercentCut(log=True)
            return
        if self._toggle_start_blocked('pctcut'):
            return

        had_prior_pct_other_mac = bool(
            self.percent_cut_active
            and self.percent_cut_device_mac
            and self.percent_cut_device_mac != mac
        )
        pct = self._clamp_percent(self.spinPercentCutMain.value())
        allow_pct = max(0, 100 - pct)
        self.percent_cut_active = True
        self.percent_cut_device_mac = mac
        self.percent_cut_device_ip = ip
        self.btnPercentCut.setText(f'■ CUT {pct}%')
        self.btnPercentCut.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        self._paint_flow_start_ui('pctcut', device)

        self._pctcut_start_gen = int(getattr(self, '_pctcut_start_gen', 0)) + 1
        pct_gen = self._pctcut_start_gen
        pct_device = dict(device)
        pct_val = pct
        pct_allow = allow_pct

        def _pctcut_deferred_start():
            if getattr(self, '_shutting_down', False):
                return
            if (
                not self.percent_cut_active
                or int(getattr(self, '_pctcut_start_gen', 0)) != pct_gen
            ):
                return
            try:
                mac = str(pct_device.get('mac') or '').strip()
                ip = str(pct_device.get('ip') or '').strip()
                if had_prior_pct_other_mac:
                    self.stopPercentCut(log=False)
                if self.mitm_shaping_active:
                    self.stop_mitm_shaping(log=False)
                    self._await_mitm_teardown_thread()
                if self.lag_active and self.lag_device_mac == mac:
                    self.stopLagSwitch(refresh_dialog=True)
                if self.dupe_active and self.dupe_device_mac == mac:
                    self.stopDupe(log=False)
                    self._flush_pending_dupe_clear_sync()
                if self._kill_ui_shows_on(mac, pct_device.get('ip'), pct_device):
                    self._clear_explicit_kill_for_flow(dict(pct_device))
                if (
                    not self.percent_cut_active
                    or int(getattr(self, '_pctcut_start_gen', 0)) != pct_gen
                ):
                    return
                device = pct_device
                pct = pct_val
                allow_pct = pct_allow
                mac = str(device.get('mac') or '').strip()
                ip = str(device.get('ip') or '').strip()
                plan = self._impairment_plan_for(device)
                if plan.is_ics_downstream:
                    if not clumsy_ics_lag_can_use_windivert(device, self.scanner):
                        self.percent_cut_active = False
                        self.percent_cut_device_mac = None
                        self.percent_cut_device_ip = None
                        self.log(
                            'Percent Cut on hotspot needs WinDivert: '
                            + clumsy_windivert_unavailable_reason(device),
                            'red',
                        )
                        self._refresh_flow_toggle_ui()
                        return
                    device = self._prepare_victim_for_impairment(dict(device), fast=True)
                    if not self._ics_apply_percent_cut_windivert(device, pct):
                        self.percent_cut_active = False
                        self.percent_cut_device_mac = None
                        self.percent_cut_device_ip = None
                        self.log(
                            'Percent Cut needs WinDivert (run as Administrator).',
                            'red',
                        )
                        self._refresh_flow_toggle_ui()
                        return
                    resolved_ip = self._ics_hotspot_victim_ip(device, pctcut=True)
                else:
                    device = self._prepare_victim_for_impairment(dict(device), fast=True)
                    self._refresh_victim_mac_from_system_arp(device)
                    mac = str(device.get('mac') or '').strip()
                    self.percent_cut_device_mac = mac
                    if not self.killer.apply_percent_cut(device, pass_percent=allow_pct):
                        self.percent_cut_active = False
                        self.percent_cut_device_mac = None
                        self.percent_cut_device_ip = None
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
                    self._log_mitm_arm_status(device, action='Percent Cut')
                    resolved_ip = clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
                        device.get('ip') or ''
                    ).strip()
                if int(getattr(self, '_pctcut_start_gen', 0)) != pct_gen:
                    return
                self.percent_cut_device_ip = resolved_ip
                self.log(
                    f'Percent Cut ON for {resolved_ip or ip}: {pct}% cut ({allow_pct}% pass)',
                    UI_LOG_VICTIM_BLOCK_FG,
                )
                self._refresh_flow_toggle_ui()
            except Exception as exc:
                self.percent_cut_active = False
                self.percent_cut_device_mac = None
                self.percent_cut_device_ip = None
                self._refresh_flow_toggle_ui()
                self.log(f'Percent Cut failed to start: {exc}', 'red')

        QTimer.singleShot(0, _pctcut_deferred_start)


    def stopPercentCut(self, log=True):
        prev_mac = self.percent_cut_device_mac
        prev_ip = getattr(self, 'percent_cut_device_ip', None)
        was_ui_on = bool(self.percent_cut_active)
        self.percent_cut_active = False
        self.percent_cut_device_mac = None
        self.percent_cut_device_ip = None
        self.btnPercentCut.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self._refresh_flow_toggle_ui()
        try:
            app = QApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.ExcludeUserInputEvents)
        except Exception:
            pass
        victim = self._resolve_pctcut_stop_snapshot(prev_mac, prev_ip)
        if victim:
            try:
                self._release_pctcut_victim_immediate(victim)
            except Exception:
                pass
        if log:
            if victim:
                ip = str(victim.get('ip') or prev_ip or '')
                still = self._percent_cut_forwarder_live(
                    str(victim.get('mac') or ''), ip
                )
                if still:
                    self.log(
                        f'Percent Cut OFF: cut still active on {ip} — toggle again',
                        'red',
                    )
                else:
                    self.log('Percent Cut OFF for ' + ip, UI_LOG_RESTORE_FG)
            elif was_ui_on:
                self.log('Percent Cut OFF', UI_LOG_RESTORE_FG)
        self._refresh_flow_toggle_ui()
