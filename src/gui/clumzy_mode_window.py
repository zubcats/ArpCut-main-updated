"""Clumzy Mode main window — ZubCut chrome, Clumzy engine only. No ARP / Killer / Npcap cut path."""
from __future__ import annotations

import sys

from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from constants import APP_DISPLAY_NAME, TABLE_HEADER_LABELS
from gui.about import About
from gui.advanced_lag_settings import AdvancedLagSettingsDialog
from gui.settings import Settings
from tools.branding import load_application_qicon, load_shell_window_icon, qicon_is_empty
from tools.clumzy_engine import load_clumzy_engine
from tools.clumzy_hotspot_view import list_hotspot_clients
from tools.clumzy_mode_profile import (
    CYCLE_SETTLE_S,
    FILTER,
    NETWORK_REMOTE,
    apply_freeze,
)
from tools.frameless_chrome import FramelessResizableMixin, setup_frameless_main_window
from tools.keybinds import keyseq_from_setting
from tools.qtools import TableRowNoCellFocusDelegate
from tools.utils_gui import (
    apply_app_global_dark_stylesheet,
    get_settings,
    is_admin,
    register_window_surface_effects,
    sync_translucent_chrome,
)
from ui.ui_main import Ui_MainWindow

BUTTON_ACTIVE_STYLE = 'background-color: #c0392b; color: white; font-weight: bold;'


class ClumzyModeWindow(FramelessResizableMixin, QMainWindow, Ui_MainWindow):
    """Replacement main window when Clumzy Mode is on. Does not construct Scanner or Killer."""

    clumzy_mode_shell = True

    def __init__(self, window_icon=None):
        super().__init__()
        self.version = '1.29'
        self.shell_icon = window_icon or load_shell_window_icon()
        if qicon_is_empty(self.shell_icon):
            self.shell_icon = load_application_qicon()
        self.icon = load_application_qicon()
        if qicon_is_empty(self.icon):
            self.icon = self.shell_icon
        self.setWindowIcon(self.shell_icon)
        self.setupUi(self)
        self._admin_elevated = bool(sys.platform == 'win32' and is_admin())
        title = (
            f'{APP_DISPLAY_NAME} — Clumzy Mode — Administrator'
            if self._admin_elevated
            else f'{APP_DISPLAY_NAME} — Clumzy Mode'
        )
        self.setWindowTitle(title)
        apply_app_global_dark_stylesheet()
        self.setStyleSheet('')

        self.gridLayout.removeWidget(self.btnSettings)
        self.gridLayout.removeWidget(self.btnAbout)
        self.gridLayout.addWidget(self.btnSettings, 0, 7, 2, 1)
        self.gridLayout.addWidget(self.btnAbout, 0, 8, 2, 1)
        for _tb in (self.btnScanEasy, self.btnScanHard, self.btnSettings, self.btnAbout):
            _tb.setMinimumHeight(50)
            _tb.setIconSize(QSize(46, 46))
            _tb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.gridLayout.setColumnStretch(0, 0)
        for _col in range(1, 9):
            self.gridLayout.setColumnStretch(_col, 1)
        self.gridLayout.removeWidget(self.lblDonate)
        self.lblDonate.hide()
        self.gridLayout.removeWidget(self.lblcenter)
        self.gridLayout.addWidget(self.lblcenter, 3, 3, 1, 4)
        self.lblcenter.setText('Clumzy Mode — hotspot (all forwarded packets)')

        self.btnScanHard.hide()
        self.btnScanEasy.setText('Refresh')
        self.btnScanEasy.setToolTip('Refresh the hotspot device list (display only).')
        self.btnScanEasy.clicked.connect(self.refresh_hotspot_table)
        self.btnSettings.setToolTip('Settings — turn Clumzy Mode off to return to normal ZubCut.')
        self.btnSettings.clicked.connect(self.openSettings)
        self.btnAbout.clicked.connect(self.openAbout)
        self.btnAbout.setIcon(self.icon)

        self._build_flow_buttons()
        self._hide_percent_cut()
        self.pgbar.setVisible(False)

        self.tableScan.setColumnCount(len(TABLE_HEADER_LABELS))
        self.tableScan.verticalHeader().setVisible(False)
        self.tableScan.setHorizontalHeaderLabels(TABLE_HEADER_LABELS)
        self.tableScan.setSelectionMode(QAbstractItemView.NoSelection)
        self.tableScan.setFocusPolicy(Qt.NoFocus)
        self.tableScan.setItemDelegate(TableRowNoCellFocusDelegate(self.tableScan))
        self.tableScan.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.settings_window = Settings(self, self.shell_icon)
        self.about_window = About(self, self.shell_icon)
        self.advanced_lag_settings_dialog = AdvancedLagSettingsDialog(self, self.shell_icon)
        self.advanced_lag_settings_dialog._clumzy_engine_host = self

        self._engine = None
        self._engine_error = ''
        try:
            self._engine = load_clumzy_engine()
            self._engine.set_network(NETWORK_REMOTE)
        except Exception as exc:
            self._engine_error = str(exc)

        self._flow = None  # None | 'kill' | 'lag' | 'dupe'
        self._want_running = False
        self._repeat_active = False
        self._adv_live = False
        self._op_busy = False
        self.mitm_shaping_active = False
        self.mitm_shaping_mac = ''
        self._mitm_adv_sched_t0 = 0.0
        self._mitm_adv_row_t0 = {}
        self._mitm_adv_last_sched = None
        self.lblleft.setWordWrap(False)
        self.lblleft.setTextFormat(Qt.PlainText)
        self.auto_stop = QTimer(self)
        self.auto_stop.setSingleShot(True)
        self.auto_stop.timeout.connect(self._on_timer_elapsed)
        self._cycle_timer = QTimer(self)
        self._cycle_timer.setSingleShot(True)
        self._cycle_timer.timeout.connect(self._finish_cycle_restart)
        self._adv_timer = QTimer(self)
        self._adv_timer.setInterval(100)
        self._adv_timer.timeout.connect(self._tick_advanced)

        self._shortcut_kill = QShortcut(QKeySequence(Qt.Key_L), self)
        self._shortcut_kill.setContext(Qt.ApplicationShortcut)
        self._shortcut_kill.setAutoRepeat(False)
        self._shortcut_kill.activated.connect(self.toggle_kill)
        self._shortcut_lag = QShortcut(QKeySequence(Qt.Key_M), self)
        self._shortcut_lag.setContext(Qt.ApplicationShortcut)
        self._shortcut_lag.setAutoRepeat(False)
        self._shortcut_lag.activated.connect(self.toggle_lag)
        self._shortcut_dupe = QShortcut(QKeySequence(Qt.Key_P), self)
        self._shortcut_dupe.setContext(Qt.ApplicationShortcut)
        self._shortcut_dupe.setAutoRepeat(False)
        self._shortcut_dupe.activated.connect(self.toggle_dupe)
        self.refresh_keyboard_shortcuts_from_settings()

        apply_app_global_dark_stylesheet()
        setup_frameless_main_window(self, title, self.shell_icon, maximizable=True)
        sync_translucent_chrome(
            [self, self.settings_window, self.about_window, self.advanced_lag_settings_dialog]
        )
        self.refresh_hotspot_table()
        if self._engine_error:
            self._log(self._engine_error, 'red')
        else:
            self._log(
                'Clumzy Mode: filter true, remote/shared-devices, Freeze (lag+drop 100). '
                'Turn Mobile Hotspot on in Windows, then Kill / Lag Switch / Dupe.',
                'white',
            )

    def _build_flow_buttons(self) -> None:
        self.btnKill = QPushButton('Kill: OFF', self.centralwidget)
        self.btnKill.setObjectName('btnKill')
        self.btnKill.setMinimumHeight(88)
        self.btnKill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        kill_font = QFont(self.btnKill.font())
        kill_font.setPointSize(13)
        kill_font.setBold(True)
        self.btnKill.setFont(kill_font)
        self.btnKill.setToolTip(
            'Kill — Start/Stop Clumzy Freeze on all hotspot forwarded packets. Shortcut: L.'
        )
        self.btnKill.pressed.connect(self.toggle_kill)

        self.btnLagSwitch = QPushButton('Lag Switch', self.centralwidget)
        self.btnLagSwitch.setObjectName('btnLagSwitch')
        self.btnLagSwitch.setMinimumHeight(72)
        self.btnLagSwitch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lag_font = QFont(self.btnLagSwitch.font())
        lag_font.setPointSize(13)
        lag_font.setBold(True)
        self.btnLagSwitch.setFont(lag_font)
        self.btnLagSwitch.setToolTip(
            'Lag Switch — Freeze for the timer, then cycle off/on (Clumzy Repeat). Shortcut: M.'
        )
        self.btnLagSwitch.pressed.connect(self.toggle_lag)

        self.btnDupe = QPushButton('Dupe', self.centralwidget)
        self.btnDupe.setObjectName('btnDupe')
        self.btnDupe.setMinimumHeight(72)
        self.btnDupe.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        dupe_font = QFont(self.btnDupe.font())
        dupe_font.setPointSize(13)
        dupe_font.setBold(True)
        self.btnDupe.setFont(dupe_font)
        self.btnDupe.setToolTip(
            'Dupe — Freeze for the duration, then stop (no repeat). Shortcut: P.'
        )
        self.btnDupe.pressed.connect(self.toggle_dupe)

        row = QWidget(self.centralwidget)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self.gridLayout.spacing())
        lay.addWidget(self.btnLagSwitch, 3)
        lay.addWidget(self.btnKill, 2)
        lay.addWidget(self.btnDupe, 3)
        self.gridLayout.addWidget(row, 5, 1, 1, 8)

        self.groupLagInline = QGroupBox('Lag Switch Controls', self.centralwidget)
        lag_l = QVBoxLayout(self.groupLagInline)
        timing = QHBoxLayout()
        timing.addWidget(QLabel('Timer', self.groupLagInline))
        self.lagSpinMain = QSpinBox(self.groupLagInline)
        self.lagSpinMain.setRange(50, 120000)
        self.lagSpinMain.setSingleStep(100)
        self.lagSpinMain.setValue(7000)
        self.lagSpinMain.setSuffix(' ms')
        timing.addWidget(self.lagSpinMain)
        lag_l.addLayout(timing)
        self.lblLagCountdownMain = QLabel('', self.groupLagInline)
        self.lblLagCountdownMain.setVisible(False)
        lag_l.addWidget(self.lblLagCountdownMain)
        self.gridLayout.addWidget(self.groupLagInline, 6, 1, 1, 4)

        self.groupDupeInline = QGroupBox('Dupe Controls', self.centralwidget)
        dupe_l = QVBoxLayout(self.groupDupeInline)
        dtiming = QHBoxLayout()
        dtiming.addWidget(QLabel('Duration', self.groupDupeInline))
        self.dupeSpinMain = QSpinBox(self.groupDupeInline)
        self.dupeSpinMain.setRange(50, 120000)
        self.dupeSpinMain.setSingleStep(100)
        self.dupeSpinMain.setValue(5000)
        self.dupeSpinMain.setSuffix(' ms')
        dtiming.addWidget(self.dupeSpinMain)
        dupe_l.addLayout(dtiming)
        self.lblDupeCountdownMain = QLabel('', self.groupDupeInline)
        self.lblDupeCountdownMain.setVisible(False)
        dupe_l.addWidget(self.lblDupeCountdownMain)
        self.gridLayout.addWidget(self.groupDupeInline, 6, 5, 1, 4)

        adv = QPushButton('Advanced Lag…', self.centralwidget)
        adv.setObjectName('btnAdvancedLag')
        adv.setMinimumHeight(36)
        adv.clicked.connect(self.open_advanced_lag)
        self.gridLayout.addWidget(adv, 8, 1, 1, 8)

        try:
            self.lagSpinMain.setValue(int(get_settings('clumzy_lag_timer_ms') or 7000))
        except Exception:
            pass
        try:
            self.dupeSpinMain.setValue(int(get_settings('clumzy_dupe_timer_ms') or 5000))
        except Exception:
            pass
        self.lagSpinMain.valueChanged.connect(self._persist_timers)
        self.dupeSpinMain.valueChanged.connect(self._persist_timers)

    def _hide_percent_cut(self) -> None:
        for name in (
            'lblPercentCut',
            'sliderPercentCutMain',
            'spinPercentCutMain',
            'btnPercentCut',
        ):
            w = getattr(self, name, None)
            if w is not None:
                w.hide()

    def _persist_timers(self, *_args) -> None:
        from tools.utils_gui import set_settings_many

        try:
            set_settings_many(
                {
                    'clumzy_lag_timer_ms': int(self.lagSpinMain.value()),
                    'clumzy_dupe_timer_ms': int(self.dupeSpinMain.value()),
                }
            )
        except Exception:
            pass

    def log(self, msg, color: str = 'white') -> None:
        from gui.logs_window import log_color_to_hex

        plain = str(msg or '')
        hex_color = log_color_to_hex(color)
        self.lblleft.setStyleSheet(
            f'QLabel#lblleft {{ color: {hex_color}; background: transparent; border: none; }}'
        )
        self.lblleft.setToolTip(plain)
        self.lblleft.setText(plain)

    def _log(self, msg, color: str = 'white') -> None:
        self.log(msg, color)

    def _sync_settings_gear_update_hint(self) -> None:
        return

    def stopLagSwitch(self) -> None:
        self._stop_engine()

    def stopDupe(self, log: bool = False) -> None:
        self._stop_engine()

    def refresh_hotspot_table(self) -> None:
        rows = list_hotspot_clients()
        self.tableScan.setRowCount(len(rows))
        for i, device in enumerate(rows):
            texts = [
                device.get('ip', ''),
                device.get('mac', ''),
                device.get('vendor', ''),
                device.get('type', ''),
                device.get('name', ''),
            ]
            for col, text in enumerate(texts):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEditable)
                self.tableScan.setItem(i, col, item)
        if rows:
            self.lblcenter.setText(f'Hotspot devices: {len(rows)} (display only — Kill hits all)')
        else:
            self.lblcenter.setText('No hotspot clients in ARP yet. Turn on Mobile Hotspot and Refresh.')

    def openSettings(self) -> None:
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def openAbout(self) -> None:
        self.about_window.show()
        self.about_window.raise_()

    def open_advanced_lag(self) -> None:
        dlg = self.advanced_lag_settings_dialog
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def refresh_keyboard_shortcuts_from_settings(self) -> None:
        s = {}
        try:
            from tools.utils_gui import import_settings

            s = import_settings()
        except Exception:
            s = {}
        self._shortcut_kill.setKey(keyseq_from_setting(s.get('key_kill'), Qt.Key_L))
        self._shortcut_lag.setKey(keyseq_from_setting(s.get('key_lag'), Qt.Key_M))
        self._shortcut_dupe.setKey(keyseq_from_setting(s.get('key_dupe'), Qt.Key_P))

    def _ensure_engine(self) -> bool:
        if self._engine is None:
            self._log(self._engine_error or 'Clumzy engine is not available.', 'red')
            return False
        return True

    def _stop_engine(self) -> None:
        self.auto_stop.stop()
        self._cycle_timer.stop()
        self._want_running = False
        self._repeat_active = False
        self._adv_live = False
        self.mitm_shaping_active = False
        self._adv_timer.stop()
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass
        self._flow = None
        self._paint_buttons()

    def _start_freeze(self) -> str | None:
        if not self._ensure_engine():
            return self._engine_error or 'no engine'
        apply_freeze(self._engine)
        self._engine.set_network(NETWORK_REMOTE)
        return self._engine.start(FILTER)

    def toggle_kill(self) -> None:
        if self._flow == 'kill':
            self._stop_engine()
            self._log('Clumzy Kill OFF.', 'white')
            return
        self._stop_engine()
        err = self._start_freeze()
        if err:
            self._log(err, 'red')
            return
        self._flow = 'kill'
        self._want_running = True
        self._paint_buttons()
        self._log('Clumzy Kill ON — Freeze on all hotspot forwarded packets.', 'white')

    def toggle_lag(self) -> None:
        if self._flow == 'lag':
            self._stop_engine()
            self._log('Clumzy Lag Switch OFF.', 'white')
            return
        self._stop_engine()
        err = self._start_freeze()
        if err:
            self._log(err, 'red')
            return
        self._flow = 'lag'
        self._want_running = True
        self._repeat_active = True
        self.auto_stop.start(max(50, int(self.lagSpinMain.value())))
        self._paint_buttons()
        self._log('Clumzy Lag Switch ON — timer with repeat.', 'white')

    def toggle_dupe(self) -> None:
        if self._flow == 'dupe':
            self._stop_engine()
            self._log('Clumzy Dupe OFF.', 'white')
            return
        self._stop_engine()
        err = self._start_freeze()
        if err:
            self._log(err, 'red')
            return
        self._flow = 'dupe'
        self._want_running = True
        self._repeat_active = False
        self.auto_stop.start(max(50, int(self.dupeSpinMain.value())))
        self._paint_buttons()
        self._log('Clumzy Dupe ON — timer without repeat.', 'white')

    def _on_timer_elapsed(self) -> None:
        if self._flow == 'lag' and self._want_running and self._repeat_active:
            if self._engine is not None:
                try:
                    self._engine.stop()
                except Exception:
                    pass
            self._cycle_timer.start(int(CYCLE_SETTLE_S * 1000))
            return
        self._stop_engine()
        self._log('Clumzy timer finished.', 'white')

    def _finish_cycle_restart(self) -> None:
        if not (self._flow == 'lag' and self._want_running and self._repeat_active):
            return
        err = self._start_freeze()
        if err:
            self._stop_engine()
            self._log(err, 'red')
            return
        self.auto_stop.start(max(50, int(self.lagSpinMain.value())))

    def _paint_buttons(self) -> None:
        self.btnKill.setStyleSheet(BUTTON_ACTIVE_STYLE if self._flow == 'kill' else '')
        self.btnLagSwitch.setStyleSheet(BUTTON_ACTIVE_STYLE if self._flow == 'lag' else '')
        self.btnDupe.setStyleSheet(BUTTON_ACTIVE_STYLE if self._flow == 'dupe' else '')
        self.btnKill.setText('■ KILL: ON' if self._flow == 'kill' else 'Kill: OFF')

    def apply_advanced_clumzy(self, settings: dict) -> None:
        """Map Advanced Lag rows onto the Clumzy engine (no MITM / Python WinDivert)."""
        del settings
        if not self._ensure_engine():
            return
        if self._flow is not None:
            self._stop_engine()
        self.mitm_shaping_active = True
        self.mitm_shaping_mac = 'hotspot (all)'
        self._adv_live = True
        self._reset_mitm_adv_sched_clock()
        err = self._apply_gated_clumzy(announce=True)
        if err:
            self.stop_advanced_clumzy()
            self._log(err, 'red')
            return
        self._adv_timer.start()
        self._log('Advanced Lag using Clumzy engine.', 'white')

    def stop_advanced_clumzy(self) -> None:
        self._adv_live = False
        self.mitm_shaping_active = False
        self._adv_timer.stop()
        self._mitm_adv_last_sched = None
        if self._flow is None and self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass

    def stop_mitm_shaping(self, log: bool = True) -> None:
        self.stop_advanced_clumzy()
        if log:
            self._log('Advanced Lag off.', 'white')

    def _mitm_adv_get(self, key: str, default=None):
        dlg = getattr(self, 'advanced_lag_settings_dialog', None)
        if dlg is not None and getattr(dlg, '_chk_adv_delay_on', None) is not None:
            try:
                return dlg.mitm_adv_settings_get(key, default)
            except Exception:
                pass
        return get_settings(key, default)

    def _reset_mitm_adv_sched_clock(self, row_prefix: str | None = None) -> None:
        from tools import mitm_adv_sched

        now = mitm_adv_sched.monotonic_now()
        if row_prefix:
            self._mitm_adv_row_t0[str(row_prefix)] = now
        else:
            self._mitm_adv_row_t0 = {p: now for p in mitm_adv_sched.ROW_PREFIXES}
            self._mitm_adv_sched_t0 = now
        self._mitm_adv_last_sched = None

    def _start_mitm_adv_schedule(self) -> None:
        if self.mitm_shaping_active and not self._adv_timer.isActive():
            self._adv_timer.start()

    def _mitm_adv_schedule_tick(self) -> None:
        self._tick_advanced()

    def _apply_gated_clumzy(self, *, announce: bool = False) -> str | None:
        from tools import mitm_adv_sched

        if not self._ensure_engine():
            return self._engine_error or 'no engine'
        now = mitm_adv_sched.monotonic_now()
        t0 = float(self._mitm_adv_sched_t0 or 0.0)
        if t0 <= 0.0:
            self._reset_mitm_adv_sched_clock()
            t0 = float(self._mitm_adv_sched_t0)
        row_t0 = dict(self._mitm_adv_row_t0 or {})
        getter = self._mitm_adv_get
        if mitm_adv_sched.all_enabled_timers_finished(now, t0, getter, row_t0):
            self.stop_mitm_shaping(log=True)
            return None
        du, dd, ju, jd, cu, cd, lu, ld, gates = mitm_adv_sched.gated_mitm_params(
            now, t0, getter, row_t0
        )
        cur = mitm_adv_sched.sched_apply_tuple(du, dd, ju, jd, cu, cd, lu, ld, gates)
        if not announce and self._mitm_adv_last_sched == cur:
            return None
        self._mitm_adv_last_sched = cur
        lag_in = max(dd, jd)
        lag_out = max(du, ju)
        lag_ms = max(lag_in, lag_out)
        if lag_ms > 0:
            self._engine.lag(1 if lag_in else 0, 1 if lag_out else 0, int(lag_ms))
            self._engine.enable('lag', True)
        else:
            self._engine.enable('lag', False)
        drop_pct = max(lu, ld)
        if drop_pct > 0:
            self._engine.drop(1 if ld else 0, 1 if lu else 0, float(drop_pct))
            self._engine.enable('drop', True)
        else:
            self._engine.enable('drop', False)
        cap_mbps = max(cu, cd)
        if cap_mbps > 0:
            kbps = max(1, int(cap_mbps * 125))
            self._engine.bandwidth(1 if cd else 0, 1 if cu else 0, kbps, 32, 1)
            self._engine.enable('bandwidth', True)
        else:
            self._engine.enable('bandwidth', False)
        for name in ('disconnect', 'throttle', 'duplicate', 'ood', 'tamper', 'reset'):
            self._engine.enable(name, False)
        if not self._engine.is_running():
            self._engine.set_network(NETWORK_REMOTE)
            return self._engine.start(FILTER)
        return None

    def _tick_advanced(self) -> None:
        if not self._adv_live or self._engine is None:
            return
        err = self._apply_gated_clumzy()
        if err:
            self.stop_advanced_clumzy()
            self._log(err, 'red')

    def quit_all(self) -> None:
        if getattr(self, '_quitting', False):
            return
        self._quitting = True
        self._stop_engine()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:
        self.quit_all()
        event.accept()


def run_clumzy_mode(qt_app, window_icon=None) -> ClumzyModeWindow:
    window = ClumzyModeWindow(window_icon=window_icon)
    window.show()
    window.raise_()
    window.activateWindow()
    return window
