"""Shared flow-net thread + teardown helpers (extracted from MainWindow)."""
from __future__ import annotations

from PyQt5.QtCore import QTimer, pyqtSlot
from PyQt5.QtWidgets import QAction, QMenu

from gui.advanced_lag_settings import AdvancedLagSettingsDialog
from tools.pfctl import _is_valid_ip
from tools.utils_gui import sync_translucent_chrome, theme_popup_menu
from gui.impairment_shared import UI_LOG_RESTORE_FG


class ImpairmentFlowNetMixin:
    def _on_main_flow_toggle_context_menu(self, pos):
        w = self.sender()
        if w is None:
            return
        menu = QMenu(self)
        theme_popup_menu(menu)
        act_adv = QAction('Advanced Lag Settings…', self)
        act_adv.triggered.connect(self._open_advanced_lag_settings)
        menu.addAction(act_adv)
        menu.exec_(w.mapToGlobal(pos))


    def _open_advanced_lag_settings(self):
        try:
            from tools.utils_gui import repair_settings

            repair_settings()
        except Exception:
            pass
        if self.advanced_lag_settings_dialog is None:
            self.advanced_lag_settings_dialog = AdvancedLagSettingsDialog(self)
            _chrome = [
                self,
                self.settings_window,
                self.about_window,
                self.device_window,
                self.traffic_window,
                self.advanced_lag_settings_dialog,
            ]
            for d in (
                getattr(self, 'lag_switch_dialog', None),
                getattr(self, 'dupe_switch_dialog', None),
            ):
                if d is not None:
                    _chrome.append(d)
            sync_translucent_chrome(_chrome)
        dlg = self.advanced_lag_settings_dialog
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()


    def _cancel_deferred_flow_starts(self) -> None:
        """Invalidate pending Lag/Dupe arm timers so exit does not re-enter Qt slots."""
        self._lag_start_gen = int(getattr(self, '_lag_start_gen', 0)) + 1
        self._dupe_start_gen = int(getattr(self, '_dupe_start_gen', 0)) + 1
        self._pctcut_start_gen = int(getattr(self, '_pctcut_start_gen', 0)) + 1
        try:
            self._dupe_arm_timer.stop()
        except Exception:
            pass


    def _teardown_all_attacks(self, *, log: bool = False) -> dict:
        """Stop lag/kill/dupe/MITM and remove all ZubCut firewall blocks (exit + startup)."""
        self._cancel_deferred_flow_starts()
        extra_ips: list = []
        for v in self.killer.killed.values():
            if isinstance(v, dict) and v.get('ip'):
                extra_ips.append(v['ip'])
        for ip in (getattr(self, 'lag_device_ip', None), getattr(self, 'dupe_device_ip', None)):
            if ip and _is_valid_ip(str(ip)):
                extra_ips.append(str(ip))
        if getattr(self, 'percent_cut_device_mac', None):
            dev = self._get_device_by_mac(self.percent_cut_device_mac)
            if dev and dev.get('ip'):
                extra_ips.append(dev['ip'])
        if getattr(self, 'mitm_shaping_mac', None):
            dev = self._get_device_by_mac(self.mitm_shaping_mac)
            if dev and dev.get('ip'):
                extra_ips.append(dev['ip'])

        self.stopLagSwitch()
        self.stopDupe(log=False)
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)
        self.stop_mitm_shaping(log=False)
        self._await_mitm_teardown_thread()
        self._stop_ics_lag_gate(join_timeout=0.5)
        self.killer.unkill_all(self.scanner)

        from tools.pfctl import teardown_all_zubcut_network_attacks

        summary = teardown_all_zubcut_network_attacks(extra_ips=extra_ips)
        self.killed_devices.clear()
        self._sync_killed_devices()
        self.lag_active = False
        self.lag_device_mac = None
        self.lag_device_ip = None
        self.dupe_active = False
        self.dupe_device_mac = None
        self.dupe_device_ip = None
        self.percent_cut_active = False
        self.percent_cut_device_mac = None
        self.percent_cut_device_ip = None
        self.mitm_shaping_active = False
        self.mitm_shaping_mac = None
        self.mitm_shaping_device_ip = None

        if log:
            removed = int(summary.get('firewall_rules_removed') or 0)
            ips = summary.get('unblocked_ips') or []
            if removed or ips:
                parts = ['Cleared active attacks on exit.']
                if removed:
                    parts.append(f'{removed} firewall rule(s)')
                if ips:
                    parts.append(f'unblocked {len(ips)} IP(s)')
                self.log(' '.join(parts), UI_LOG_RESTORE_FG)
        return summary


    def _sync_inline_flow_controls_enabled(self):
        lag_locked = bool(self.lag_active and self.lag_device_mac)
        self.lagDirBoth.setEnabled(not lag_locked)
        self.lagDirIncoming.setEnabled(not lag_locked)
        self.lagDirOutgoing.setEnabled(not lag_locked)
        dupe_locked = bool(self.dupe_active and self.dupe_device_mac)
        self.dupeDirBoth.setEnabled(not dupe_locked)
        self.dupeDirIncoming.setEnabled(not dupe_locked)
        self.dupeDirOutgoing.setEnabled(not dupe_locked)


    @pyqtSlot(object)
    def _on_flow_net_main_done(self, cb) -> None:
        """Run flow-net completion callbacks on the GUI thread (never from a worker)."""
        if callable(cb):
            try:
                cb()
            except Exception:
                pass


    def _run_on_flow_net_thread(self, fn, *, main_after=None) -> None:
        """Run WinDivert/firewall work off the GUI thread (shared dupe_net pool)."""
        ex = getattr(self, '_dupe_net_executor', None)
        if ex is None:
            try:
                fn()
            except Exception:
                pass
            if main_after is not None:
                QTimer.singleShot(0, main_after)
            return

        def _wrapped() -> None:
            try:
                fn()
            except Exception:
                pass

        fut = ex.submit(_wrapped)
        if main_after is not None:
            fut.add_done_callback(lambda _f: self.flow_net_main_done.emit(main_after))


    def _refresh_flow_toggle_ui(self, *, fast: bool = False):
        """Synchronize Lag/Dupe/Kill button text after cross-flow toggles."""
        self._updateLagSwitchButtonState()
        self._updateDupeButtonState()
        self._updateKillButtonState(fast=fast)
        self._updatePercentCutButtonState()
        self._sync_inline_flow_controls_enabled()
