import os
import re
import sys
import time

from pyperclip import copy

from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QMessageBox, \
                            QMenu, QSystemTrayIcon, QAction, QPushButton, \
                            QDialog, QFormLayout, QDialogButtonBox, QSpinBox, \
                            QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QGroupBox, \
                            QSizePolicy, QShortcut, QAbstractSpinBox, QAbstractItemView, QLineEdit, QSlider, \
                            QTextEdit, QPlainTextEdit, QWidget
from PyQt5.QtGui import QPixmap, QIcon, QFont, QKeySequence, QBrush, QFontMetrics
from PyQt5.QtCore import Qt, QObject, QTimer, QSize, QElapsedTimer, QThread, pyqtSignal, QEvent
try:
    from PyQt5.QtWinExtras import QWinTaskbarButton
except Exception:
    QWinTaskbarButton = None

from ui.ui_main import Ui_MainWindow

from gui.settings import Settings
from gui.about import About
from gui.device import Device
from .traffic import Traffic

from networking.scanner import Scanner
from networking.killer import Killer

from tools.qtools import colored_item, MsgType, Buttons, clickable, TableRowNoCellFocusDelegate
from tools.utils_gui import (
    set_settings,
    get_settings,
    import_settings,
    apply_app_global_dark_stylesheet,
    sync_translucent_chrome,
    register_window_surface_effects,
    table_row_hover_chrome,
    table_row_selection_chrome,
)
from tools.frameless_chrome import (
    FramelessResizableMixin,
    setup_frameless_main_window,
    CustomTitleBar,
)
from tools.keybinds import keyseq_from_setting
from tools.branding import (
    load_application_qicon,
    qicon_is_empty,
    crop_logo_content,
    LOGO_UI_CONTENT_FRACTION,
)
from tools.utils import (
    goto,
    is_connected,
    get_default_iface,
)
from tools.tray_cleanup import hide_all_system_tray_icons
from tools.pfctl import block_ip, unblock_ip

from assets import *

from bridge import ScanThread  # UpdateThread disabled for fork

_SETTINGS_BTN_TIP = 'Settings - Configure scan options and network interface'
# Foreground: HEAD every 15 min only while the app is active (timer paused when not).
_UPDATE_POLL_INTERVAL_MS = 15 * 60 * 1000
# Background: still check once per day so tray/minimized sessions learn about new builds.
_UPDATE_POLL_DAILY_MS = 24 * 60 * 60 * 1000


class _UpdateStatusPollThread(QThread):
    """HEAD the update URL off the UI thread (avoids hangs on slow networks)."""

    done = pyqtSignal(bool, str)

    def run(self):
        from tools.updater_core import get_update_status

        try:
            avail, label = get_update_status()
        except Exception:
            avail, label = False, ''
        self.done.emit(avail, label)

import constants as _zcut_constants
from constants import *

# Frozen/CI builds may ship an older constants module; keep defaults in sync with src/constants.py.
# Must use QPushButton#btnSettings so this wins over _main_chrome_action_buttons_qss() on the app sheet.
_SETTINGS_BTN_UPDATE_STYLE = getattr(
    _zcut_constants,
    'UPDATE_AVAILABLE_SETTINGS_GEAR_QSS',
    (
        'QPushButton#btnSettings { background-color: #1a3d28; color: #d8f0e4; font-weight: bold; '
        'border: 1px solid #2d5738; border-radius: 4px; }'
    ),
)
ADMIN_DEVICE_TABLE_ROW_BG = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_BG', '#5D706E')
ADMIN_DEVICE_TABLE_ROW_FG = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_FG', '#eef1f0')
UI_LOG_VICTIM_BLOCK_FG = getattr(_zcut_constants, 'UI_LOG_VICTIM_BLOCK_FG', '#32716D')
UI_LOG_RESTORE_FG = getattr(_zcut_constants, 'UI_LOG_RESTORE_FG', ADMIN_DEVICE_TABLE_ROW_BG)

# Killed device row: dark red matched to experimental admin row darkness (see ADMIN_DEVICE_TABLE_ROW_*).
_DEVICE_ROW_KILL_BG = '#3d1a1a'
_DEVICE_ROW_KILL_FG = '#e8d0d0'
_DEVICE_ROW_KILL_HOVER_BG = '#502626'
_DEVICE_ROW_KILL_HOVER_FG = '#f5e6e6'
# Killed row while also selected (or among several killed): slightly lifted from base kill red.
_DEVICE_ROW_KILL_SELECTED_BG = '#4a2828'
_DEVICE_ROW_KILL_SELECTED_FG = '#f5e8e8'
_DEVICE_ROW_KILL_SEL_HOVER_BG = '#5c3232'
_DEVICE_ROW_KILL_SEL_HOVER_FG = '#fff8f8'

# from qt_material import build_stylesheet

def _focus_widget_absorbs_letter_key(widget):
    """Avoid stealing letter shortcuts only while typing in text-entry fields."""
    if widget is None:
        return False
    # Spin boxes use an internal QLineEdit editor; do not block global shortcuts there.
    if isinstance(widget, QLineEdit):
        try:
            if isinstance(widget.parent(), QAbstractSpinBox):
                return False
        except Exception:
            pass
        return True
    return isinstance(widget, (QTextEdit, QPlainTextEdit))


def _chrome_pushbutton_hover_inline_qss(watched_btn=None) -> str:
    """Programmatic hover for icon chrome (Fusion + qdark); same palette for all toolbar buttons."""
    return (
        'background-color: #383838; color: #d0d0d0; border: 1px solid #383838; border-radius: 4px;'
    )


class _ChromePushButtonHoverFilter(QObject):
    """
    Global QSS :hover is unreliable for icon-only QPushButtons (Fusion + qdarkstyle).
    Paint hover by setting a widget-level stylesheet on Enter and restoring on Leave.
    """

    def __init__(self, main_window, watched_buttons):
        super().__init__(main_window)
        self._m = main_window
        self._watched = frozenset(watched_buttons)

    def eventFilter(self, obj, event):
        if obj not in self._watched:
            return False
        t = event.type()
        if t == QEvent.Enter:
            if not obj.isEnabled():
                return False
            if (obj.styleSheet() or '').strip():
                return False
            obj.setStyleSheet(_chrome_pushbutton_hover_inline_qss(obj))
            return False
        if t == QEvent.Leave:
            self._m._restore_chrome_button_surface(obj)
            return False
        return False


class LagSwitchDialog(FramelessResizableMixin, QDialog):
    """Non-modal panel: edit lag / allow times, then toggle lag switch on or off."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('zubcutLagDupeDialog')
        self._main = parent
        # Only pull timings from MainWindow when the panel is opened (after hide), not on every showEvent.
        self._reload_timing_on_next_show = True
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowTitle('Lag Switch')
        self.setModal(False)
        self.setMinimumWidth(350)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        lag_icon = parent.icon if parent else None
        root.addWidget(
            CustomTitleBar(
                self,
                'Lag Switch',
                lag_icon,
                maximizable=False,
                caption_accent=ADMIN_DEVICE_TABLE_ROW_BG,
            )
        )

        body = QWidget(self)
        body.setObjectName('zubcutDialogBody')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 12)

        self.btnLagStartStop = QPushButton('Start', body)
        self.btnLagStartStop.setMinimumHeight(50)
        self.btnLagStartStop.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btnLagStartStop.setToolTip(
            'Start or stop intermittent lag for the device selected in the main list. '
            'Shortcut: M when this window is active (not in ms fields).'
        )
        self.btnLagStartStop.clicked.connect(self._on_lag_start_stop_clicked)
        self._shortcut_m = QShortcut(QKeySequence(Qt.Key_M), self)
        self._shortcut_m.setContext(Qt.WindowShortcut)
        self._shortcut_m.setAutoRepeat(False)
        self._shortcut_m.activated.connect(self._on_m_key_pressed)
        # Lag uses the global ApplicationShortcut path as the single source of truth.
        # Keep this object for key updates/tooltips, but disable it to avoid split handling.
        self._shortcut_m.setEnabled(False)
        layout.addWidget(self.btnLagStartStop)

        # Direction selection
        self.dir_group = QGroupBox('Traffic Direction to Block', body)
        dir_layout = QVBoxLayout(self.dir_group)

        self.dirBoth = QCheckBox('Both directions (full lag)')
        self.dirBoth.setChecked(True)
        self.dirBoth.setToolTip('Block all traffic during lag phase - causes complete freeze')

        self.dirIncoming = QCheckBox('Incoming only (receive lag)')
        self.dirIncoming.setToolTip('Block only incoming traffic - you can send but not receive')

        self.dirOutgoing = QCheckBox('Outgoing only (send lag)')
        self.dirOutgoing.setToolTip('Block only outgoing traffic - you can receive but not send')

        self.dirBoth.toggled.connect(self._on_both_toggled)

        dir_layout.addWidget(self.dirBoth)
        dir_layout.addWidget(self.dirIncoming)
        dir_layout.addWidget(self.dirOutgoing)
        for _cb in (self.dirBoth, self.dirIncoming, self.dirOutgoing):
            _cb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout.addWidget(self.dir_group)

        # Timing section
        self.timing_group = QGroupBox('Timing', body)
        timing_layout = QFormLayout(self.timing_group)

        self.lagSpin = QSpinBox(self.timing_group)
        self.lagSpin.setRange(1, 2147483647)
        self.lagSpin.setSingleStep(100)
        self.lagSpin.setValue(1500)
        self.lagSpin.setSuffix(' ms')
        timing_layout.addRow('Lag duration (block time)', self.lagSpin)

        self.normalSpin = QSpinBox(self.timing_group)
        self.normalSpin.setRange(25, 2147483647)
        self.normalSpin.setSingleStep(25)
        self.normalSpin.setValue(1500)
        self.normalSpin.setSuffix(' ms')
        timing_layout.addRow('Normal duration (allow time)', self.normalSpin)
        self.lagSpin.valueChanged.connect(self._on_timing_spin_changed)
        self.normalSpin.valueChanged.connect(self._on_timing_spin_changed)

        layout.addWidget(self.timing_group)

        info = QLabel(
            'Cycle: Lag time (top) = block + MITM on. Normal time (bottom) = full allow '
            '(firewall off and ARP restored so traffic bypasses this PC). Then repeat.',
            body,
        )
        info.setWordWrap(True)
        info.setStyleSheet('color: gray; font-size: 10px; padding: 5px;')
        layout.addWidget(info)

        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel('Presets:'))

        self._preset_buttons = []
        btn_fast = QPushButton('Fast (500/500)')
        btn_fast.clicked.connect(lambda: self._set_preset(500, 500))
        self._preset_buttons.append(btn_fast)
        preset_layout.addWidget(btn_fast)

        btn_med = QPushButton('Medium (1500/1500)')
        btn_med.clicked.connect(lambda: self._set_preset(1500, 1500))
        self._preset_buttons.append(btn_med)
        preset_layout.addWidget(btn_med)

        btn_heavy = QPushButton('Heavy (9000/100)')
        btn_heavy.clicked.connect(lambda: self._set_preset(9000, 100))
        self._preset_buttons.append(btn_heavy)
        preset_layout.addWidget(btn_heavy)

        layout.addLayout(preset_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, body)
        buttons.rejected.connect(self.hide)
        layout.addWidget(buttons)

        root.addWidget(body, 1)
        for _pb in self.findChildren(QPushButton):
            _pb.setAutoDefault(False)
            _pb.setDefault(False)
        self._zubcut_use_translucent_surface = False
        register_window_surface_effects(self)

    def _on_m_key_pressed(self):
        # WindowShortcut on this dialog only fires when focus is here; avoid activeWindow()
        # checks — they fail for some frameless / top-level dialog focus paths on Windows.
        if _focus_widget_absorbs_letter_key(self.focusWidget()):
            return
        self._on_lag_start_stop_clicked()

    def showEvent(self, event):
        super().showEvent(event)
        if self._reload_timing_on_next_show:
            self._load_timing_from_main()
            self._reload_timing_on_next_show = False
        self.refresh_toggle_state()

    def hideEvent(self, event):
        self._reload_timing_on_next_show = True
        super().hideEvent(event)

    def _load_timing_from_main(self):
        if not self._main:
            return
        m = self._main
        self.lagSpin.setValue(m.lag_block_ms)
        self.normalSpin.setValue(m.lag_release_ms)
        self._apply_direction_to_ui(getattr(m, 'lag_direction', 'both'))

    def _apply_direction_to_ui(self, direction):
        self.dirBoth.blockSignals(True)
        self.dirIncoming.blockSignals(True)
        self.dirOutgoing.blockSignals(True)
        if direction == 'in':
            self.dirBoth.setChecked(False)
            self.dirIncoming.setChecked(True)
            self.dirOutgoing.setChecked(False)
        elif direction == 'out':
            self.dirBoth.setChecked(False)
            self.dirIncoming.setChecked(False)
            self.dirOutgoing.setChecked(True)
        else:
            self.dirBoth.setChecked(True)
            self.dirIncoming.setChecked(False)
            self.dirOutgoing.setChecked(False)
        self.dirBoth.blockSignals(False)
        self.dirIncoming.blockSignals(False)
        self.dirOutgoing.blockSignals(False)

    def _set_timing_controls_enabled(self, enabled):
        """Lock direction/presets while lagging this device; block/allow ms stay editable."""
        self.dir_group.setEnabled(enabled)
        for b in self._preset_buttons:
            b.setEnabled(enabled)
        self.timing_group.setEnabled(True)

    def _on_timing_spin_changed(self, *_):
        main = self._main
        if not main or not main.lag_active or not main.lag_device_mac:
            return
        if not main.tableScan.selectedItems():
            return
        try:
            dev = main.current_index()
        except Exception:
            return
        if dev['mac'] != main.lag_device_mac:
            return
        lag_ms, normal_ms, direction = self.values()
        main.applyLagSwitchSettings(lag_ms, normal_ms, direction)

    def refresh_toggle_state(self):
        """Sync Start/Stop button and locked state with the main window (e.g. after row change or stop)."""
        if not self._main:
            return
        main = self._main
        # Show the real active state, even if selection changed/lost.
        on = bool(main.lag_active and main.lag_device_mac)
        self.btnLagStartStop.blockSignals(True)
        if on:
            self.btnLagStartStop.setText('Stop')
            self.btnLagStartStop.setStyleSheet(main.BUTTON_ACTIVE_STYLE)
        else:
            self.btnLagStartStop.setText('Start')
            self.btnLagStartStop.setStyleSheet(main.BUTTON_NORMAL_STYLE)
        self.btnLagStartStop.blockSignals(False)
        self._set_timing_controls_enabled(not on)

    def _reject_enable(self):
        self.refresh_toggle_state()

    def _on_lag_start_stop_clicked(self):
        main = self._main
        if not main:
            return
        # If lag is active, any toggle press means STOP active lag immediately.
        if main.lag_active and main.lag_device_mac:
            lag_edge = 'stop'
            if main._ignore_duplicate_toggle_edge('lag', main.lag_device_mac, lag_edge):
                return
            main.stopLagSwitch()
            return

        device = None
        if main.tableScan.selectedItems():
            try:
                device = main.current_index()
            except Exception:
                device = None
        if device is None:
            # Focus can move to this dialog and clear selectedItems() while currentRow still points
            # at the intended victim. Use currentRow as a fallback so the Lag keybind still works.
            row = main.tableScan.currentRow()
            if 0 <= row < len(main.scanner.devices):
                device = main.scanner.devices[row]
        if device is None:
            pinned_mac = getattr(main, '_lag_dialog_target_mac', None)
            if pinned_mac:
                device = main._get_device_by_mac(pinned_mac) or main._victim_record_for_mac(pinned_mac)
        deb_mac = device.get('mac') if isinstance(device, dict) else None
        lag_edge = 'start'
        if main._ignore_duplicate_toggle_edge('lag', deb_mac, lag_edge):
            return
        if not device:
            main.log('No device selected', 'red')
            return
        if device['admin']:
            main.log('Cannot lag admin device', UI_LOG_VICTIM_BLOCK_FG)
            return
        if main._toggle_start_blocked('lag'):
            return
        lag_ms, normal_ms, direction = self.values()
        main.applyLagSwitchSettings(lag_ms, normal_ms, direction)
        main.startLagSwitch(device)

    def _on_both_toggled(self, checked):
        if checked:
            self.dirIncoming.setChecked(False)
            self.dirOutgoing.setChecked(False)

    def _set_preset(self, lag, normal):
        self.lagSpin.setValue(lag)
        self.normalSpin.setValue(normal)

    def values(self):
        """Returns (lag_ms, normal_ms, direction)"""
        direction = 'both'
        if self.dirIncoming.isChecked() and not self.dirOutgoing.isChecked():
            direction = 'in'
        elif self.dirOutgoing.isChecked() and not self.dirIncoming.isChecked():
            direction = 'out'
        elif self.dirIncoming.isChecked() and self.dirOutgoing.isChecked():
            direction = 'both'
        return self.lagSpin.value(), self.normalSpin.value(), direction


class DupeDialog(FramelessResizableMixin, QDialog):
    """One-shot timed block: lag for N ms, then fully release (no repeat)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('zubcutLagDupeDialog')
        self._main = parent
        self._reload_on_next_show = True
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowTitle('Dupe')
        self.setModal(False)
        self.setMinimumWidth(350)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        dupe_icon = parent.icon if parent else None
        root.addWidget(
            CustomTitleBar(
                self,
                'Dupe',
                dupe_icon,
                maximizable=False,
                caption_accent=ADMIN_DEVICE_TABLE_ROW_BG,
            )
        )

        body = QWidget(self)
        body.setObjectName('zubcutDialogBody')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 12)

        self.btnDupeRun = QPushButton('Run', body)
        self.btnDupeRun.setMinimumHeight(50)
        self.btnDupeRun.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btnDupeRun.setToolTip(
            'Run a single lag burst for the device selected in the main list, then stop completely. '
            'Shortcut: P when this window is active (not in ms fields).'
        )
        self.btnDupeRun.clicked.connect(self._on_run_clicked)
        layout.addWidget(self.btnDupeRun)

        self.lblDupeCountdown = QLabel(body)
        self.lblDupeCountdown.setAlignment(Qt.AlignCenter)
        self.lblDupeCountdown.setWordWrap(True)
        cd_font = QFont(self.lblDupeCountdown.font())
        cd_font.setPointSize(13)
        cd_font.setBold(True)
        self.lblDupeCountdown.setFont(cd_font)
        self.lblDupeCountdown.setVisible(False)
        layout.addWidget(self.lblDupeCountdown)

        self._shortcut_p = QShortcut(QKeySequence(Qt.Key_P), self)
        self._shortcut_p.setContext(Qt.WindowShortcut)
        self._shortcut_p.setAutoRepeat(False)
        self._shortcut_p.activated.connect(self._on_p_key_pressed)
        # Dupe uses the global ApplicationShortcut path as the single source of truth.
        # Keep this object for key updates/tooltips, but disable local routing.
        self._shortcut_p.setEnabled(False)

        self.dir_group = QGroupBox('Traffic Direction to Block', body)
        dir_layout = QVBoxLayout(self.dir_group)
        self.dirBoth = QCheckBox('Both directions (full lag)')
        self.dirBoth.setChecked(True)
        self.dirIncoming = QCheckBox('Incoming only (receive lag)')
        self.dirOutgoing = QCheckBox('Outgoing only (send lag)')
        self.dirBoth.toggled.connect(self._on_both_toggled)
        dir_layout.addWidget(self.dirBoth)
        dir_layout.addWidget(self.dirIncoming)
        dir_layout.addWidget(self.dirOutgoing)
        for _cb in (self.dirBoth, self.dirIncoming, self.dirOutgoing):
            _cb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout.addWidget(self.dir_group)

        self.timing_group = QGroupBox('Duration', body)
        timing_layout = QFormLayout(self.timing_group)
        self.dupeSpin = QSpinBox(self.timing_group)
        self.dupeSpin.setRange(1, 2147483647)
        self.dupeSpin.setSingleStep(100)
        self.dupeSpin.setValue(5000)
        self.dupeSpin.setSuffix(' ms')
        timing_layout.addRow('Lag duration (one shot)', self.dupeSpin)
        layout.addWidget(self.timing_group)

        info = QLabel(
            'Runs one block window for the duration above, then removes firewall rules and ARP spoof. '
            'Does not repeat — use Lag Switch for on/off cycles.',
            body,
        )
        info.setWordWrap(True)
        info.setStyleSheet('color: gray; font-size: 10px; padding: 5px;')
        layout.addWidget(info)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, body)
        buttons.rejected.connect(self.hide)
        layout.addWidget(buttons)

        root.addWidget(body, 1)
        for _pb in self.findChildren(QPushButton):
            _pb.setAutoDefault(False)
            _pb.setDefault(False)
        self._zubcut_use_translucent_surface = False
        register_window_surface_effects(self)

    def _on_p_key_pressed(self):
        if _focus_widget_absorbs_letter_key(self.focusWidget()):
            return
        self._on_run_clicked()

    def showEvent(self, event):
        super().showEvent(event)
        if self._reload_on_next_show:
            self._load_from_main()
            self._reload_on_next_show = False
        self.refresh_toggle_state()

    def hideEvent(self, event):
        self._reload_on_next_show = True
        super().hideEvent(event)

    def _load_from_main(self):
        m = self._main
        if not m:
            return
        self.dupeSpin.setValue(getattr(m, 'dupe_duration_ms', 5000))
        self._apply_direction_to_ui(getattr(m, 'dupe_direction', 'both'))

    def _apply_direction_to_ui(self, direction):
        self.dirBoth.blockSignals(True)
        self.dirIncoming.blockSignals(True)
        self.dirOutgoing.blockSignals(True)
        if direction == 'in':
            self.dirBoth.setChecked(False)
            self.dirIncoming.setChecked(True)
            self.dirOutgoing.setChecked(False)
        elif direction == 'out':
            self.dirBoth.setChecked(False)
            self.dirIncoming.setChecked(False)
            self.dirOutgoing.setChecked(True)
        else:
            self.dirBoth.setChecked(True)
            self.dirIncoming.setChecked(False)
            self.dirOutgoing.setChecked(False)
        self.dirBoth.blockSignals(False)
        self.dirIncoming.blockSignals(False)
        self.dirOutgoing.blockSignals(False)

    def _on_both_toggled(self, checked):
        if checked:
            self.dirIncoming.setChecked(False)
            self.dirOutgoing.setChecked(False)

    def _set_controls_enabled(self, enabled):
        self.dir_group.setEnabled(enabled)

    def refresh_toggle_state(self):
        main = self._main
        if not main:
            return
        # Show actual active state regardless of current selection.
        on = bool(main.dupe_active and main.dupe_device_mac)
        self.btnDupeRun.blockSignals(True)
        if on:
            self.btnDupeRun.setText('Stop')
            self.btnDupeRun.setStyleSheet(main.BUTTON_ACTIVE_STYLE)
        else:
            self.btnDupeRun.setText('Run')
            self.btnDupeRun.setStyleSheet(main.BUTTON_NORMAL_STYLE)
        self.btnDupeRun.blockSignals(False)
        self._set_controls_enabled(not on)
        if on and main and getattr(main, 'dupe_active', False):
            self.set_dupe_countdown(main.dupe_remaining_ms())
        else:
            self.set_dupe_countdown(None)

    def set_dupe_countdown(self, left_ms):
        """Show remaining dupe time; pass None when idle."""
        if left_ms is None or left_ms <= 0:
            self.lblDupeCountdown.setVisible(False)
            self.lblDupeCountdown.setText('')
            return
        self.lblDupeCountdown.setVisible(True)
        left_ms = max(0, int(left_ms))
        sec = left_ms / 1000.0
        if sec >= 60:
            whole = int(sec)
            m, s = divmod(whole, 60)
            self.lblDupeCountdown.setText(f'Time left: {m}:{s:02d}')
        else:
            self.lblDupeCountdown.setText(f'Time left: {sec:.1f} s')

    def values(self):
        direction = 'both'
        if self.dirIncoming.isChecked() and not self.dirOutgoing.isChecked():
            direction = 'in'
        elif self.dirOutgoing.isChecked() and not self.dirIncoming.isChecked():
            direction = 'out'
        elif self.dirIncoming.isChecked() and self.dirOutgoing.isChecked():
            direction = 'both'
        return self.dupeSpin.value(), direction

    def _on_run_clicked(self):
        main = self._main
        if not main:
            return
        # If dupe is active, any toggle press means STOP active dupe immediately.
        if main.dupe_active and main.dupe_device_mac:
            dupe_edge = 'stop'
            if main._ignore_duplicate_toggle_edge('dupe', main.dupe_device_mac, dupe_edge):
                return
            main.stopDupe()
            return

        device = None
        if main.tableScan.selectedItems():
            try:
                device = main.current_index()
            except Exception:
                device = None
        if device is None:
            row = main.tableScan.currentRow()
            if 0 <= row < len(main.scanner.devices):
                device = main.scanner.devices[row]
        if device is None:
            pinned_mac = getattr(main, '_dupe_dialog_target_mac', None)
            if pinned_mac:
                device = main._get_device_by_mac(pinned_mac) or main._victim_record_for_mac(pinned_mac)
        deb_mac = device.get('mac') if isinstance(device, dict) else None
        dupe_edge = 'start'
        if main._ignore_duplicate_toggle_edge('dupe', deb_mac, dupe_edge):
            return
        if not device:
            main.log('No device selected', 'red')
            return
        if device['admin']:
            main.log('Cannot dupe admin device', UI_LOG_VICTIM_BLOCK_FG)
            return
        if main._toggle_start_blocked('dupe'):
            return
        ms, direction = self.values()
        main.dupe_duration_ms = ms
        main.dupe_direction = direction
        main.startDupe(device, ms, direction)



class ElmoCut(FramelessResizableMixin, QMainWindow, Ui_MainWindow):
    def __init__(self, window_icon=None):
        super().__init__()
        self.version = '1.29'
        if window_icon is not None:
            self.icon = window_icon
        else:
            self.icon = load_application_qicon()
            if qicon_is_empty(self.icon):
                self.icon = self.processIcon(app_icon, crop_margins=True)

        # Add window icon
        self.setWindowIcon(self.icon)
        self.setupUi(self)
        self.setWindowTitle(APP_DISPLAY_NAME)
        apply_app_global_dark_stylesheet()
        self.setStyleSheet('')
        # Rebalance top toolbar row so right-side empty space is used more evenly.
        self.gridLayout.removeWidget(self.btnSettings)
        self.gridLayout.removeWidget(self.btnAbout)
        self.gridLayout.addWidget(self.btnSettings, 0, 6, 2, 1)
        self.gridLayout.addWidget(self.btnAbout, 0, 7, 2, 2)
        self.gridLayout.setColumnStretch(0, 0)
        for _col in range(1, 9):
            self.gridLayout.setColumnStretch(_col, 1)

        # Legacy "ZubCut" label read like a clickable tab; remove it and widen the center status strip.
        self.gridLayout.removeWidget(self.lblDonate)
        self.lblDonate.hide()
        self.gridLayout.removeWidget(self.lblcenter)
        self.gridLayout.addWidget(self.lblcenter, 3, 3, 1, 4)

        # Left status strip (lblleft): elide long lines to fit; full text in tooltip.
        self._status_strip_plain = None
        self._status_strip_color = 'white'

        # Space was bound in the .ui to ARP scan; only fire when the main window is foreground.
        self.btnScanEasy.setShortcut(QKeySequence())
        sc_arp_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc_arp_space.setContext(Qt.WindowShortcut)
        sc_arp_space.setAutoRepeat(False)
        sc_arp_space.activated.connect(self._shortcut_scan_easy)

        self._shortcut_kill_l = QShortcut(QKeySequence(Qt.Key_L), self)
        self._shortcut_kill_l.setContext(Qt.ApplicationShortcut)
        self._shortcut_kill_l.setAutoRepeat(False)
        self._shortcut_kill_l.activated.connect(self._shortcut_main_l)
        self._shortcut_lag_global = QShortcut(QKeySequence(Qt.Key_M), self)
        self._shortcut_lag_global.setContext(Qt.ApplicationShortcut)
        self._shortcut_lag_global.setAutoRepeat(False)
        self._shortcut_lag_global.activated.connect(self._shortcut_global_lag)
        self._shortcut_dupe_global = QShortcut(QKeySequence(Qt.Key_P), self)
        self._shortcut_dupe_global.setContext(Qt.ApplicationShortcut)
        self._shortcut_dupe_global.setAutoRepeat(False)
        self._shortcut_dupe_global.activated.connect(self._shortcut_global_dupe)
        self._shortcut_pctcut_global = QShortcut(QKeySequence(Qt.Key_K), self)
        self._shortcut_pctcut_global.setContext(Qt.ApplicationShortcut)
        self._shortcut_pctcut_global.setAutoRepeat(False)
        self._shortcut_pctcut_global.activated.connect(self._shortcut_global_pctcut)

        # Main Props
        self.scanner = Scanner()
        self.killer = Killer()
        self.killed_devices = {}  # MAC -> bool kill toggle state
        # Per-MAC intent generation for kill toggle; delayed OFF reinforcement only runs
        # when generation still matches (prevents stale delayed actions from reapplying).
        self._kill_intent_seq = {}
        # Per-flow OFF intent generation (lag/dupe/unkill-all).
        self._flow_off_intent_seq = {}
        self.lag_active = False
        self.lag_block_ms = 9000
        self.lag_release_ms = 100
        self.lag_device_mac = None
        self.lag_direction = 'both'  # 'both', 'in', or 'out'
        self.lag_timer = QTimer(self)
        self.lag_timer.setSingleShot(True)
        self.lag_timer.setTimerType(Qt.PreciseTimer)
        self.lag_timer.timeout.connect(self._lag_phase_tick)
        # False: firewall block is active (victim is in "lag" phase). True: allow window (rules cleared).
        self._lag_in_allow_phase = False
        # Last started lag target; used on stop if the device row is missing from the scan list.
        self._lag_device_snapshot = None

        self.dupe_active = False
        self.dupe_device_mac = None
        self.dupe_direction = 'both'
        self.dupe_duration_ms = 5000
        self.percent_cut_active = False
        self.percent_cut_device_mac = None
        self._lag_dialog_target_mac = None
        self._dupe_dialog_target_mac = None
        self.dupe_timer = QTimer(self)
        self.dupe_timer.setSingleShot(True)
        self.dupe_timer.setTimerType(Qt.PreciseTimer)
        self.dupe_timer.timeout.connect(self._dupe_timer_fired)
        self._dupe_elapsed = QElapsedTimer()
        self._dupe_countdown_timer = QTimer(self)
        self._dupe_countdown_timer.setInterval(100)
        self._dupe_countdown_timer.timeout.connect(self._tick_dupe_countdown)

        # Button active state styles
        self.BUTTON_ACTIVE_STYLE = "background-color: #c0392b; color: white; font-weight: bold;"
        # Idle chrome for Kill / Lag / Dupe comes from utils_gui title-bar-matched QSS (object names).
        self.BUTTON_NORMAL_STYLE = ""

        # Settings props
        self.minimize = True
        self.remember = False
        self.autoupdate = True

        self.from_tray = False

        # Threading
        self.scan_thread = ScanThread()
        self.scan_thread.thread_finished.connect(self.ScanThread_Reciever)
        self.scan_thread.progress.connect(self.pgbar.setValue)

        # Update thread disabled for fork
        # self.update_thread = UpdateThread()
        # self.update_thread.thread_finished.connect(self.UpdateThread_Reciever)
        
        # Initialize other sub-windows
        self.settings_window = Settings(self, self.icon)
        self.about_window = About(self, self.icon)
        self.device_window = Device(self, self.icon)
        self.traffic_window = Traffic(self, self.icon)

        # Connect buttons with icons and tooltips
        self.buttons = [
            (self.btnScanEasy,   self.scanEasy,      scan_easy_icon,  'ARP Scan - Fast network scan using ARP requests (may miss some devices). Shortcut: Space (only while this main window is focused).'),
            (self.btnScanHard,   self.scanHard,      scan_hard_icon,  'Ping Scan - Thorough scan using ICMP ping (slower but finds all devices)'),
            (self.btnSettings,   self.openSettings,  settings_icon,   'Settings - Configure scan options and network interface'),
            (self.btnAbout,      self.openAbout,     None,            f'About {APP_DISPLAY_NAME} - View credits and version info')
        ] 
        
        for btn, btn_func, btn_icon, btn_tip in self.buttons:
            btn.setToolTip(btn_tip)
            btn.clicked.connect(btn_func)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setAttribute(Qt.WA_StyledBackground, True)
            if btn_icon is not None:
                btn.setIcon(self.processIcon(btn_icon))
        self.btnAbout.setIcon(self.icon)
        # Match ui_main (40); larger icons clip in the top grid cell.
        self.btnAbout.setIconSize(QSize(40, 40))

        self.btnKill = QPushButton(self.centralwidget)
        self.btnKill.setObjectName('btnKill')
        self.btnKill.setAttribute(Qt.WA_StyledBackground, True)
        self.btnKill.setAutoDefault(False)
        self.btnKill.setDefault(False)
        self.btnKill.setMinimumHeight(88)
        self.btnKill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btnKill.setToolTip(
            'Kill toggle — Turn blocking on or off for the selected device. '
            'Shortcut: L (only while the main ZubCut window is the active window).'
        )
        self._btn_kill_icon = self.processIcon(kill_icon)
        self.btnKill.setIcon(self._btn_kill_icon)
        self.btnKill.setMinimumWidth(130)
        self.btnKill.setIconSize(QSize(56, 56))
        kill_font = QFont(self.btnKill.font())
        kill_font.setPointSize(13)
        kill_font.setBold(True)
        self.btnKill.setFont(kill_font)
        # Use pressed instead of clicked so fast double-clicks count as two toggles.
        self.btnKill.pressed.connect(lambda: self.toggleKill('mouse_pressed'))

        self.btnLagSwitch = QPushButton('Lag Switch', self.centralwidget)
        self.btnLagSwitch.setObjectName('btnLagSwitch')
        self.btnLagSwitch.setAttribute(Qt.WA_StyledBackground, True)
        self.btnLagSwitch.setAutoDefault(False)
        self.btnLagSwitch.setDefault(False)
        self.btnLagSwitch.setMinimumHeight(72)
        self.btnLagSwitch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btnLagSwitch.setToolTip(
            'Lag Switch — start/stop intermittent blocking for selected device. '
            'Timing/direction controls are always visible below. Shortcut: M.'
        )
        self.gridLayout.addWidget(self.btnLagSwitch, 5, 1, 1, 3)
        self.btnLagSwitch.pressed.connect(lambda: self._shortcut_global_lag())
        lag_font = QFont(self.btnLagSwitch.font())
        lag_font.setPointSize(13)
        lag_font.setBold(True)
        self.btnLagSwitch.setFont(lag_font)

        self.gridLayout.addWidget(self.btnKill, 5, 4, 1, 2)

        self.btnDupe = QPushButton('Dupe', self.centralwidget)
        self.btnDupe.setObjectName('btnDupe')
        self.btnDupe.setAttribute(Qt.WA_StyledBackground, True)
        self.btnDupe.setAutoDefault(False)
        self.btnDupe.setDefault(False)
        self.btnDupe.setMinimumHeight(72)
        self.btnDupe.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        dupe_font = QFont(self.btnDupe.font())
        dupe_font.setPointSize(14)
        dupe_font.setBold(True)
        self.btnDupe.setFont(dupe_font)
        self.btnDupe.setToolTip(
            'Dupe — one-shot lag for a set duration, then full stop. '
            'Duration/direction controls are always visible below. Shortcut: P.'
        )
        self.gridLayout.addWidget(self.btnDupe, 5, 6, 1, 3)
        self.btnDupe.pressed.connect(lambda: self._shortcut_global_dupe())

        self.groupLagInline = QGroupBox('Lag Switch Controls', self.centralwidget)
        self.groupLagInline.setObjectName('groupLagInline')
        self.groupLagInline.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.groupLagInlineLayout = QVBoxLayout(self.groupLagInline)
        self.groupLagInlineLayout.setContentsMargins(8, 8, 8, 8)
        self.groupLagInlineLayout.setSpacing(4)
        self.lagTimingRow = QHBoxLayout()
        self.lagTimingRow.addWidget(QLabel('Lag', self.groupLagInline))
        self.lagSpinMain = QSpinBox(self.groupLagInline)
        self.lagSpinMain.setRange(1, 2147483647)
        self.lagSpinMain.setSingleStep(100)
        self.lagSpinMain.setValue(9000)
        self.lagSpinMain.setSuffix(' ms')
        self.lagTimingRow.addWidget(self.lagSpinMain)
        self.lagTimingRow.addWidget(QLabel('Normal', self.groupLagInline))
        self.normalSpinMain = QSpinBox(self.groupLagInline)
        self.normalSpinMain.setRange(25, 2147483647)
        self.normalSpinMain.setSingleStep(25)
        self.normalSpinMain.setValue(100)
        self.normalSpinMain.setSuffix(' ms')
        self.lagTimingRow.addWidget(self.normalSpinMain)
        self.groupLagInlineLayout.addLayout(self.lagTimingRow)
        self.lagDirRow = QHBoxLayout()
        self.lagDirBoth = QCheckBox('Both', self.groupLagInline)
        self.lagDirBoth.setChecked(True)
        self.lagDirIncoming = QCheckBox('In', self.groupLagInline)
        self.lagDirOutgoing = QCheckBox('Out', self.groupLagInline)
        self.lagDirBoth.toggled.connect(
            lambda checked: checked and (self.lagDirIncoming.setChecked(False), self.lagDirOutgoing.setChecked(False))
        )
        self.lagDirRow.addWidget(QLabel('Block', self.groupLagInline))
        self.lagDirRow.addWidget(self.lagDirBoth)
        self.lagDirRow.addWidget(self.lagDirIncoming)
        self.lagDirRow.addWidget(self.lagDirOutgoing)
        self.groupLagInlineLayout.addLayout(self.lagDirRow)
        self.gridLayout.addWidget(self.groupLagInline, 6, 1, 1, 4)

        self.groupDupeInline = QGroupBox('Dupe Controls', self.centralwidget)
        self.groupDupeInline.setObjectName('groupDupeInline')
        self.groupDupeInline.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.groupDupeInlineLayout = QVBoxLayout(self.groupDupeInline)
        self.groupDupeInlineLayout.setContentsMargins(8, 8, 8, 8)
        self.groupDupeInlineLayout.setSpacing(4)
        self.dupeTimingRow = QHBoxLayout()
        self.dupeTimingRow.addWidget(QLabel('Duration', self.groupDupeInline))
        self.dupeSpinMain = QSpinBox(self.groupDupeInline)
        self.dupeSpinMain.setRange(1, 2147483647)
        self.dupeSpinMain.setSingleStep(100)
        self.dupeSpinMain.setValue(5000)
        self.dupeSpinMain.setSuffix(' ms')
        self.dupeTimingRow.addWidget(self.dupeSpinMain)
        self.groupDupeInlineLayout.addLayout(self.dupeTimingRow)
        self.dupeDirRow = QHBoxLayout()
        self.dupeDirBoth = QCheckBox('Both', self.groupDupeInline)
        self.dupeDirBoth.setChecked(True)
        self.dupeDirIncoming = QCheckBox('In', self.groupDupeInline)
        self.dupeDirOutgoing = QCheckBox('Out', self.groupDupeInline)
        self.dupeDirBoth.toggled.connect(
            lambda checked: checked and (self.dupeDirIncoming.setChecked(False), self.dupeDirOutgoing.setChecked(False))
        )
        self.dupeDirRow.addWidget(QLabel('Block', self.groupDupeInline))
        self.dupeDirRow.addWidget(self.dupeDirBoth)
        self.dupeDirRow.addWidget(self.dupeDirIncoming)
        self.dupeDirRow.addWidget(self.dupeDirOutgoing)
        self.groupDupeInlineLayout.addLayout(self.dupeDirRow)
        self.lblDupeCountdownMain = QLabel('', self.groupDupeInline)
        self.lblDupeCountdownMain.setObjectName('lblDupeCountdownMain')
        self.lblDupeCountdownMain.setVisible(False)
        self.groupDupeInlineLayout.addWidget(self.lblDupeCountdownMain)
        self.gridLayout.addWidget(self.groupDupeInline, 6, 5, 1, 4)

        self.lblPercentCut = QLabel('Cut %', self.centralwidget)
        self.lblPercentCut.setObjectName('lblPercentCut')
        self.lblPercentCut.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self.gridLayout.addWidget(self.lblPercentCut, 7, 1, 1, 1)

        self.sliderPercentCutMain = QSlider(Qt.Horizontal, self.centralwidget)
        self.sliderPercentCutMain.setObjectName('sliderPercentCutMain')
        self.sliderPercentCutMain.setRange(1, 100)
        self.sliderPercentCutMain.setSingleStep(1)
        self.gridLayout.addWidget(self.sliderPercentCutMain, 7, 2, 1, 3)

        self.spinPercentCutMain = QSpinBox(self.centralwidget)
        self.spinPercentCutMain.setObjectName('spinPercentCutMain')
        self.spinPercentCutMain.setRange(1, 100)
        self.spinPercentCutMain.setSuffix('%')
        self.gridLayout.addWidget(self.spinPercentCutMain, 7, 5, 1, 1)

        self.btnPercentCut = QPushButton('Percent Cut: OFF', self.centralwidget)
        self.btnPercentCut.setObjectName('btnPercentCut')
        self.btnPercentCut.setAttribute(Qt.WA_StyledBackground, True)
        self.btnPercentCut.setAutoDefault(False)
        self.btnPercentCut.setDefault(False)
        self.btnPercentCut.setMinimumHeight(44)
        self.btnPercentCut.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btnPercentCut.setToolTip(
            'Percent Cut toggle — applies percentage-based traffic cut to selected device. '
            'Shortcut: K (main app window in foreground).'
        )
        self.gridLayout.addWidget(self.btnPercentCut, 7, 6, 1, 3)
        self.btnPercentCut.pressed.connect(lambda: self.togglePercentCut('mouse_pressed'))

        self.sliderPercentCutMain.valueChanged.connect(self.spinPercentCutMain.setValue)
        self.spinPercentCutMain.valueChanged.connect(self.sliderPercentCutMain.setValue)
        self.spinPercentCutMain.valueChanged.connect(self._on_percent_cut_value_changed)
        self.sliderPercentCutMain.setValue(self._percent_cut_value())

        self.lag_switch_dialog = None
        self.dupe_switch_dialog = None
        self.gridLayout.setSpacing(4)
        self.gridLayout.setVerticalSpacing(4)
        self.setMinimumSize(QSize(800, 560))

        self.refresh_keyboard_shortcuts_from_settings()

        self.pgbar.setVisible(False)

        # Table Widget
        self.tableScan.itemClicked.connect(self.deviceClicked)
        self.tableScan.itemDoubleClicked.connect(self.deviceDoubleClicked)
        self.tableScan.cellClicked.connect(self.cellClicked)
        self.tableScan.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableScan.customContextMenuRequested.connect(self.table_context_menu)
        self.tableScan.setColumnCount(len(TABLE_HEADER_LABELS))
        self.tableScan.verticalHeader().setVisible(False)
        self.tableScan.setHorizontalHeaderLabels(TABLE_HEADER_LABELS)
        _hh = self.tableScan.horizontalHeader()
        _hh.setContextMenuPolicy(Qt.CustomContextMenu)
        _hh.customContextMenuRequested.connect(self._scan_table_header_context_menu)
        self._sync_scan_table_column_settings()

        self._table_hover_row = -1
        _tv = self.tableScan.viewport()
        _tv.setMouseTracking(True)
        _tv.installEventFilter(self)
        sm = self.tableScan.selectionModel()
        sm.selectionChanged.connect(self._on_table_selection_for_row_hover)
        sm.currentChanged.connect(self._on_table_selection_for_row_hover)
        self.tableScan.itemSelectionChanged.connect(self._on_table_selection_for_row_hover)
        self.tableScan.currentCellChanged.connect(self._on_table_selection_for_row_hover)
        self.tableScan.setItemDelegate(TableRowNoCellFocusDelegate(self.tableScan))
        self.tableScan.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tableScan.setSelectionMode(QAbstractItemView.SingleSelection)

        '''
           System tray icon and it's tray menu
        '''
        show_option = QAction('Show', self)
        hide_option = QAction('Hide', self)
        quit_option = QAction('Quit', self)
        show_option.triggered.connect(self.trayShowClicked)
        hide_option.triggered.connect(self.hide_all)
        quit_option.triggered.connect(self.quit_all)

        tray_menu = QMenu()
        tray_menu.addAction(show_option)
        tray_menu.addAction(hide_option)
        tray_menu.addSeparator()
        self.traffic_option = QAction('Traffic for Selected', self)
        self.traffic_option.triggered.connect(self.openTraffic)
        tray_menu.addAction(self.traffic_option)
        tray_menu.addAction(quit_option)
        
        # Parent the tray to the QApplication, not the main window, so teardown order
        # does not drop the icon before hide() runs (reduces ghost icons on Windows).
        self.tray_icon = QSystemTrayIcon(QApplication.instance())
        self.tray_icon.setIcon(self.icon)
        self.tray_icon.setToolTip(APP_DISPLAY_NAME)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self.tray_clicked)
        QApplication.instance().aboutToQuit.connect(hide_all_system_tray_icons)

        # Taskbar button (Windows only)
        self.taskbar_button = None
        self.taskbar_progress = None

        # Apply global QSS after every named chrome QPushButton exists (earlier apply skipped
        # Lag/Kill/Dupe and broke Fusion :hover on icon-only toolbar buttons).
        apply_app_global_dark_stylesheet()
        self._repolish_chrome_pushbuttons()

        setup_frameless_main_window(self, APP_DISPLAY_NAME, self.icon, maximizable=True)
        _chrome_windows = [
            self,
            self.settings_window,
            self.about_window,
            self.device_window,
            self.traffic_window,
        ]
        sync_translucent_chrome(_chrome_windows)

        self.applySettings()
        self._updateKillButtonState()
        self._updateLagSwitchButtonState()
        self._updateDupeButtonState()
        self._updatePercentCutButtonState()
        self._apply_inline_panel_styles()
        self._sync_inline_flow_controls_enabled()

        _chrome_btns = (
            self.btnScanEasy,
            self.btnScanHard,
            self.btnSettings,
            self.btnAbout,
            self.btnKill,
            self.btnLagSwitch,
            self.btnDupe,
            self.btnPercentCut,
        )
        self._chrome_hover_filter = _ChromePushButtonHoverFilter(self, _chrome_btns)
        for _b in _chrome_btns:
            _b.installEventFilter(self._chrome_hover_filter)

    @staticmethod
    def processIcon(icon_data, crop_margins=False):
        """
        Create QIcon from embedded image bytes with a size ladder (better tray/title scaling).
        crop_margins: only for the ZubCut mark (same padded artwork as zubcut_icon.png).
        """
        pix = QPixmap()
        icon = QIcon()
        pix.loadFromData(icon_data)
        if pix.isNull():
            return icon
        if crop_margins:
            pix = crop_logo_content(pix, LOGO_UI_CONTENT_FRACTION)
        for s in (16, 24, 32, 48, 64, 128, 256):
            icon.addPixmap(
                pix.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation),
                QIcon.Normal,
                QIcon.Off,
            )
        icon.addPixmap(pix, QIcon.Normal, QIcon.Off)
        return icon
    
    def setImage(self, widget, raw_image):
        pix = QPixmap()
        pix.loadFromData(raw_image)
        widget.setPixmap(pix)
    
    def connected(self, show_msg_box=False):
        """
        Prompt when disconnected
        """
        # If interface is NULL, try to reinitialize
        if self.scanner.iface.name == 'NULL':
            self.scanner.iface = get_default_iface()
            self.scanner.init()
        
        if is_connected(current_iface=self.scanner.iface):
            return True
        self.log('Connection lost!', 'red')
        if show_msg_box:
            QMessageBox.critical(self, APP_DISPLAY_NAME, 'Connection Lost!')
        return False

    def _apply_status_strip_elide(self):
        """Re-render lblleft with ellipsis when text exceeds available width."""
        text = self._status_strip_plain
        if text is None:
            return
        color = self._status_strip_color
        w = self.lblleft.width()
        if w > 16:
            fm = QFontMetrics(self.lblleft.font())
            elided = fm.elidedText(text, Qt.ElideRight, max(w - 8, 16))
        else:
            max_chars = 48
            elided = text if len(text) <= max_chars else (text[: max_chars - 1] + '\u2026')
        self.lblleft.setText(f"<font color='{color}'>{elided}</font>")

    def log(self, text, color='white'):
        """
        Print log info at left label (elided if long; hover shows full text).
        """
        self._status_strip_plain = text
        self._status_strip_color = color
        self.lblleft.setToolTip(text)
        self._apply_status_strip_elide()
        QTimer.singleShot(0, self._apply_status_strip_elide)
    
    def openSettings(self):
        """
        Open settings window
        """
        self.settings_window.hide()
        self.settings_window.loadInterfaces()
        self.settings_window.currentSettings()
        self.settings_window.show()
        self.settings_window.setWindowState(Qt.WindowNoState)

    def openAbout(self):
        """
        Open about window
        """
        self.about_window.hide()
        self.about_window.show()
    
    def openTraffic(self):
        if not self.tableScan.selectedItems():
            self.log('No device selected', 'red')
            return
        device = self.current_index()
        if device['admin']:
            self.log('Admin device', UI_LOG_RESTORE_FG)
            return
        victim_ip = device['ip']
        iface = self.scanner.iface.name
        self.traffic_window.stop()
        self.traffic_window.start(victim_ip, iface)
        self.traffic_window.hide()
        self.traffic_window.show()
        self.traffic_window.setWindowState(Qt.WindowNoState)

    def table_context_menu(self, pos):
        menu = QMenu(self)
        act_traffic = QAction('Traffic for Selected', self)
        act_probe = QAction('Probe IP…', self)
        act_traffic.triggered.connect(self.openTraffic)
        act_probe.triggered.connect(self.probe_ip)
        menu.addAction(act_traffic)
        menu.addAction(act_probe)
        menu.addSeparator()
        self._append_scan_column_visibility_actions(menu)
        menu.exec_(self.tableScan.viewport().mapToGlobal(pos))

    def _scan_table_header_context_menu(self, pos):
        menu = QMenu(self)
        self._append_scan_column_visibility_actions(menu)
        menu.exec_(self.tableScan.horizontalHeader().mapToGlobal(pos))

    def _append_scan_column_visibility_actions(self, menu):
        act_mac = QAction('MAC Address', self)
        act_mac.setCheckable(True)
        act_mac.blockSignals(True)
        act_mac.setChecked(not self.tableScan.isColumnHidden(SCAN_TABLE_COLUMN_MAC))
        act_mac.blockSignals(False)
        act_mac.toggled.connect(
            lambda c, col=SCAN_TABLE_COLUMN_MAC: self._set_scan_table_column_visible(col, c)
        )
        menu.addAction(act_mac)
        act_v = QAction('Vendor', self)
        act_v.setCheckable(True)
        act_v.blockSignals(True)
        act_v.setChecked(not self.tableScan.isColumnHidden(SCAN_TABLE_COLUMN_VENDOR))
        act_v.blockSignals(False)
        act_v.toggled.connect(
            lambda c, col=SCAN_TABLE_COLUMN_VENDOR: self._set_scan_table_column_visible(col, c)
        )
        menu.addAction(act_v)

    def _set_scan_table_column_visible(self, col, visible):
        self.tableScan.setColumnHidden(col, not visible)
        key = 'show_scan_mac_column' if col == SCAN_TABLE_COLUMN_MAC else 'show_scan_vendor_column'
        set_settings(key, bool(visible))
        self.resizeEvent()

    def _sync_scan_table_column_settings(self):
        try:
            mac = bool(get_settings('show_scan_mac_column'))
            ven = bool(get_settings('show_scan_vendor_column'))
        except Exception:
            mac, ven = False, False
        self.tableScan.setColumnHidden(SCAN_TABLE_COLUMN_MAC, not mac)
        self.tableScan.setColumnHidden(SCAN_TABLE_COLUMN_VENDOR, not ven)
        self.resizeEvent()

    def probe_ip(self):
        from PyQt5.QtWidgets import QInputDialog
        ip, ok = QInputDialog.getText(self, 'Probe IP', 'Enter IP to probe:')
        if not ok or not ip:
            return
        self.log(f'Probing {ip}...', 'aqua')
        hit = self.scanner.probe_ip(ip)
        if hit:
            self.log(f'Discovered {hit[0]} {hit[1]}', UI_LOG_RESTORE_FG)
            self.showDevices()
        else:
            self.log('No response', 'red')

    def applySettings(self):
        """
        Apply saved settings
        """
        self.settings_window.updateElmocutSettings()

    def trayShowClicked(self):
        self.show()
        # Restore window state if was minimized before hidden
        self.setWindowState(Qt.WindowNoState)
        self.activateWindow()

    def tray_clicked(self, event):
        """
        Show main window when tray icon is left-clicked
        """
        if event == QSystemTrayIcon.Trigger:
            self.trayShowClicked()

    def hide_all(self):
        """
        Hide option for tray (Hides window and settings)
        """
        self.hide()
        self.settings_window.hide()
        self.about_window.hide()

    def quit_all(self):
        """
        Unkill any killed device on exit from tray icon
        """
        _q_ips = [v.get('ip') for v in self.killer.killed.values() if v.get('ip')]
        self.killer.unkill_all()
        for _ip in _q_ips:
            try:
                unblock_ip(_ip)
            except Exception:
                pass
        self.stopLagSwitch()
        self.stopDupe(log=False)
        self.stopPercentCut(log=False)
        self.settings_window.close()
        self.about_window.close()
        hide_all_system_tray_icons()
        self.from_tray = True
        self.close()

    def showEvent(self, event):
        """
        https://stackoverflow.com/a/60123914/5305953
        Connect TaskBar icon to progressbar
        """
        super().showEvent(event)
        if QWinTaskbarButton is None:
            return
        if getattr(self, '_taskbar_progress_linked', False):
            return
        self._taskbar_progress_linked = True
        self.taskbar_button = QWinTaskbarButton()
        self.taskbar_progress = self.taskbar_button.progress()
        self.taskbar_button.setWindow(self.windowHandle())
        self.pgbar.valueChanged.connect(self.taskbar_progress.setValue)

    def resizeEvent(self, event=True):
        """
        Auto resize table widget columns dynamically
        """
        label_count = len(TABLE_HEADER_LABELS)
        for i in range(label_count):
            self.tableScan.setColumnWidth(i, self.tableScan.width() // label_count)
        self._apply_status_strip_elide()

    def _repolish_chrome_pushbuttons(self):
        """Re-resolve app QSS on toolbar + bottom chrome (Fusion hover on icon QPushButtons)."""
        app = QApplication.instance()
        if app is None:
            return
        st = app.style()
        for w in (
            self.btnScanEasy,
            self.btnScanHard,
            self.btnSettings,
            self.btnAbout,
            self.btnKill,
            self.btnLagSwitch,
            self.btnDupe,
        ):
            st.unpolish(w)
            st.polish(w)

    def _restore_chrome_button_surface(self, btn):
        """Clear programmatic hover stylesheet; restore Kill/Lag/Dupe/Settings special chrome."""
        try:
            if btn is self.btnSettings:
                self._sync_settings_gear_update_hint()
            elif btn is self.btnKill:
                self._updateKillButtonState()
            elif btn is self.btnLagSwitch:
                self._updateLagSwitchButtonState()
            elif btn is self.btnDupe:
                self._updateDupeButtonState()
            else:
                btn.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        except RuntimeError:
            pass

    def closeEvent(self, event):
        """
        Always exit on window close to avoid background instances blocking reinstalls.
        Use explicit tray Hide to keep app running in background.
        """
        self.stopLagSwitch()
        self.stopDupe(log=False)
        # If event recieved from tray icon
        if self.from_tray:
            hide_all_system_tray_icons()
            event.accept()
            return

        # Close button path: unkill all and shutdown.
        _x_ips = [v.get('ip') for v in self.killer.killed.values() if v.get('ip')]
        self.killer.unkill_all()
        for _ip in _x_ips:
            try:
                unblock_ip(_ip)
            except Exception:
                pass
        self._sync_killed_devices()
        self.settings_window.close()
        self.about_window.close()

        self.hide()
        hide_all_system_tray_icons()

        event.accept()

    def current_index(self):
        return self.scanner.devices[self.tableScan.currentRow()]
    
    def cellClicked(self, row, column):
        """
        Copy selected cell data to clipboard
        """
        # Get current row
        device = self.current_index()

        # Get cell text using dict.values instead of .itemAt()
        cell = list(device.values())[column]
        
        if len(cell) > 20:
            cell = cell[:20] + '...'
        
        self.lblcenter.setText(cell)
        copy(cell)

    def deviceClicked(self):
        """
        Disable per-device controls when an admin row is selected.
        """
        not_enabled = not self.current_index()['admin']
        
        self.btnKill.setEnabled(not_enabled)
        self.btnLagSwitch.setEnabled(not_enabled)
        self.btnDupe.setEnabled(not_enabled)
        self.groupLagInline.setEnabled(not_enabled)
        self.groupDupeInline.setEnabled(not_enabled)
        
        self._updateKillButtonState()
        self._updateLagSwitchButtonState()
        self._updateDupeButtonState()
        self._sync_inline_flow_controls_enabled()
        self._repaint_all_table_rows_for_hover()
        self._schedule_table_selection_repaint()

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
    
    def deviceDoubleClicked(self):
        """
        Open device info window (when not admin)
        """
        device = self.current_index()
        if device['admin']:
            self.log('Admin device', color=UI_LOG_RESTORE_FG)
            return
        
        self.device_window.load(device, self.tableScan.currentRow())
        self.device_window.hide()
        self.device_window.show()
        self.device_window.setWindowState(Qt.WindowNoState)
    
    def fillTableCell(self, row, column, text, colors=None, *, selectable=True):
        if colors is None:
            colors = []
        # Center text in table cell
        ql = QTableWidgetItem()
        ql.setText(text)
        ql.setTextAlignment(Qt.AlignCenter)
        if selectable:
            ql.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        else:
            ql.setFlags(Qt.ItemIsEnabled)

        if colors:
            colored_item(ql, *colors)
        
        # Add cell to the specific location
        self.tableScan.setItem(row, column, ql)

    def eventFilter(self, obj, event):
        """Whole-row hover on the device table (viewport coords)."""
        if obj is self.tableScan.viewport():
            et = event.type()
            if et == QEvent.MouseMove:
                row = self.tableScan.rowAt(event.pos().y())
                n = self.tableScan.rowCount()
                if row < 0 or row >= n:
                    self._update_table_hover_row(-1)
                else:
                    self._update_table_hover_row(row)
            elif et == QEvent.Leave:
                self._update_table_hover_row(-1)
        return super().eventFilter(obj, event)

    def _table_row_is_selected(self, row):
        if row < 0:
            return False
        for ix in self.tableScan.selectedIndexes():
            if ix.isValid() and ix.row() == row:
                return True
        cur = self.tableScan.currentIndex()
        return cur.isValid() and cur.row() == row

    def _schedule_table_selection_repaint(self):
        """Selection model can commit after our slot; repaint next tick so brushes match."""
        QTimer.singleShot(0, self._repaint_all_table_rows_for_hover)

    def _device_row_blocked_chrome(self, device):
        """
        True when this row should use kill-row styling: explicit kill, or lag/dupe victim
        (lag allow-phase temporarily removes the MAC from killer.killed — still show red).
        """
        if not device or device.get('admin'):
            return False
        mac = device['mac']
        if mac in self.killer.killed:
            return True
        if getattr(self, 'lag_active', False) and self.lag_device_mac == mac:
            return True
        if getattr(self, 'dupe_active', False) and self.dupe_device_mac == mac:
            return True
        return False

    def _table_hover_cell_palette(self, row, device):
        """
        Return (bg, fg) for every cell in the row, or None to clear to stylesheet (alternating rows).
        """
        admin_colors = [ADMIN_DEVICE_TABLE_ROW_BG, ADMIN_DEVICE_TABLE_ROW_FG]
        if device.get('admin'):
            return tuple(admin_colors)
        blocked = self._device_row_blocked_chrome(device)
        selected = self._table_row_is_selected(row)
        hovered = row == getattr(self, '_table_hover_row', -1)
        hover_bg, hover_fg = table_row_hover_chrome()
        sel_bg, sel_fg = table_row_selection_chrome()
        if blocked:
            if selected:
                if hovered:
                    return _DEVICE_ROW_KILL_SEL_HOVER_BG, _DEVICE_ROW_KILL_SEL_HOVER_FG
                return _DEVICE_ROW_KILL_SELECTED_BG, _DEVICE_ROW_KILL_SELECTED_FG
            if hovered:
                return _DEVICE_ROW_KILL_HOVER_BG, _DEVICE_ROW_KILL_HOVER_FG
            return _DEVICE_ROW_KILL_BG, _DEVICE_ROW_KILL_FG
        if selected:
            return sel_bg, sel_fg
        if hovered:
            return hover_bg, hover_fg
        return None

    def _repaint_table_row_for_hover(self, row):
        if row < 0 or row >= self.tableScan.rowCount():
            return
        if row >= len(self.scanner.devices):
            return
        device = self.scanner.devices[row]
        ncols = self.tableScan.columnCount()
        pal = self._table_hover_cell_palette(row, device)
        for c in range(ncols):
            item = self.tableScan.item(row, c)
            if item is None:
                continue
            if pal is None:
                item.setBackground(QBrush())
                item.setForeground(QBrush())
            else:
                colored_item(item, pal[0], pal[1])

    def _update_table_hover_row(self, new_row):
        old = getattr(self, '_table_hover_row', -1)
        if new_row == old:
            return
        self._table_hover_row = new_row
        if old >= 0:
            self._repaint_table_row_for_hover(old)
        if new_row >= 0:
            self._repaint_table_row_for_hover(new_row)

    def _repaint_all_table_rows_for_hover(self):
        for r in range(self.tableScan.rowCount()):
            self._repaint_table_row_for_hover(r)

    def _on_table_selection_for_row_hover(self, *_args):
        self._repaint_all_table_rows_for_hover()

    def fillTableRow(self, row, device):
        for column, text in enumerate(device.values()):
            # Skip 'admin' key
            if type(text) == bool:
                continue
            
            if device['admin']:
                admin_colors = [ADMIN_DEVICE_TABLE_ROW_BG, ADMIN_DEVICE_TABLE_ROW_FG]
                self.fillTableCell(row, column, text, admin_colors, selectable=False)
            else:
                if self._device_row_blocked_chrome(device):
                    kill_colors = (
                        [_DEVICE_ROW_KILL_SELECTED_BG, _DEVICE_ROW_KILL_SELECTED_FG]
                        if self._table_row_is_selected(row)
                        else [_DEVICE_ROW_KILL_BG, _DEVICE_ROW_KILL_FG]
                    )
                else:
                    kill_colors = []
                self.fillTableCell(row, column, text, kill_colors)

    def showDevices(self):
        """
        View scanlist devices with correct colors processed
        """
        # Ensure "Me" and "Router" are always shown even if scan hasn't run
        if not self.scanner.devices or not any(d.get('type') == 'Me' for d in self.scanner.devices):
            try:
                self.scanner.add_me()
            except Exception:
                pass
        if not self.scanner.devices or not any(d.get('type') == 'Router' for d in self.scanner.devices):
            try:
                self.scanner.add_router()
            except Exception:
                pass
        
        current_row = self.tableScan.currentRow()
        selected_mac = None
        selected = self._get_selected_device()
        if selected:
            selected_mac = selected.get('mac')
        elif 0 <= current_row < len(self.scanner.devices):
            # Fallback before table is rebuilt: preserve current row's MAC identity when possible.
            selected_mac = self.scanner.devices[current_row].get('mac')
        self.tableScan.clearSelection()
        self.tableScan.clearContents()
        self.tableScan.setRowCount(len(self.scanner.devices))

        for row, device in enumerate(self.scanner.devices):
            self.fillTableRow(row, device)

        self._table_hover_row = -1
        
        status = f'{len(self.scanner.devices) - 2} devices' \
                 f' ({len(self.killer.killed)} killed)'
        
        status_tray = f'Devices Found: {len(self.scanner.devices) - 2}\n' \
                      f'Devices Killed: {len(self.killer.killed)}\n' \
                      f'Interface: {self.scanner.iface.name}'
        
        self.lblright.setText(status)
        self.tray_icon.setToolTip(status_tray)

        # Restore selection by MAC identity first (row index can move after rescans),
        # then fall back to the first non-admin row.
        restore_row = -1
        if selected_mac:
            for i, d in enumerate(self.scanner.devices):
                if d.get('mac') == selected_mac and not d.get('admin'):
                    restore_row = i
                    break
        if restore_row < 0:
            for i, d in enumerate(self.scanner.devices):
                if not d.get('admin'):
                    restore_row = i
                    break
        if 0 <= restore_row < len(self.scanner.devices) and not self.scanner.devices[restore_row].get('admin'):
            self.tableScan.selectRow(restore_row)
            self.tableScan.setCurrentCell(restore_row, 0)
            self.deviceClicked()
        else:
            self._updateKillButtonState()
            self._updateLagSwitchButtonState()
            self._updateDupeButtonState()
            self.lblcenter.setText('Nothing Selected')

        self._repaint_all_table_rows_for_hover()
        self._schedule_table_selection_repaint()
    
    def processDevices(self):
        """
        Rekill any paused device after scan
        """
        self.tableScan.clearSelection()

        # first device in list is the router
        self.killer.router = self.scanner.router

        # re-kill paused and update to current devices
        self.killer.rekill_stored(self.scanner.devices)
        self._sync_killed_devices()
        
        # re-kill saved devices after exit
        for rem_device in self.scanner.devices:
            if rem_device['mac'] in get_settings('killed') * self.remember:
                self.killer.kill(rem_device)

        # Killer holds ARP for lag/dupe too; Kill button tracks explicit kill / restore only.
        for mac in self.killer.killed:
            self.killed_devices[mac] = True
        self._sync_killed_devices()

        # clear old database
        self.killer.release()

        self.log(
            f'Found {len(self.scanner.devices) - 2} devices.',
            UI_LOG_RESTORE_FG,
        )

        self.showDevices()

    # @check_connection
    def kill(self):
        """
        Apply ARP spoofing to selected device
        """
        if not self.connected():
            return
        
        if not self.tableScan.selectedItems():
            self.log('No device selected', 'red')
            return

        device = self.current_index()
        
        if device['mac'] in self.killer.killed:
            self.log('Device is already killed', 'red')
            return
        
        # Killing process
        self._ensure_network_context_for_victim(device)
        self.killer.kill(device)
        try:
            iface = self.scanner.iface.name if self.scanner.iface else 'en0'
            block_ip(iface, device['ip'], 'both')
        except Exception:
            pass
        self.killed_devices[device['mac']] = True
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
        self.log('Killed ' + device['ip'], UI_LOG_VICTIM_BLOCK_FG)
        self._updateKillButtonState()
        
        self.showDevices()
    
    # @check_connection
    def unkill(self):
        """
        Disable ARP spoofing on the selected device (internal / API).
        Clears lag switch and dupe burst for that flow.
        """
        self.stopLagSwitch()
        self.stopDupe(log=False)
        if not self.connected():
            return
        
        if not self.tableScan.selectedItems():
            self.log('No device selected', 'red')
            return

        device = self.current_index()
            
        if device['mac'] not in self.killer.killed:
            self.log('Device is already unkilled', 'red')
            return

        victim = self._victim_record_for_mac(device['mac']) or device
        self._ensure_network_context_for_victim(victim)
        try:
            unblock_ip(victim.get('ip') or '')
        except Exception:
            pass
        self.killer.unkill(victim)
        self.killed_devices[device['mac']] = False
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
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
        self.stopPercentCut(log=False)
        if not self.connected():
            return
        
        self.killer.kill_all(self.scanner.devices)
        for v in list(self.killer.killed.values()):
            try:
                self._ensure_network_context_for_victim(v)
                iface = self.scanner.iface.name if self.scanner.iface else 'en0'
                block_ip(iface, v['ip'], 'both')
            except Exception:
                pass
        for mac in self.killer.killed:
            self.killed_devices[mac] = True
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
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
        self.stopPercentCut(log=False)
        if not self.connected():
            return
        
        victims_before = [dict(v) for v in self.killer.killed.values()]
        for v in victims_before:
            try:
                unblock_ip(v.get('ip') or '')
            except Exception:
                pass
        self.killer.unkill_all()
        for victim in victims_before:
            mac = victim.get('mac')
            if not mac:
                continue
            # OFF-only reinforcement for bulk unkill uses same timings as kill toggle OFF.
            self.killer.reinforce_restore(victim)
            off_seq = self._bump_flow_off_intent('all', mac)
            self._schedule_flow_off_reinforce('all', mac, off_seq, 60, victim)
            self._schedule_flow_off_reinforce('all', mac, off_seq, 180, victim)
        self.killed_devices.clear()
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
        self.log('Unkilled All devices', UI_LOG_RESTORE_FG)

        self._updateKillButtonState()
        self.showDevices()

    def scanEasy(self):
        """
        Easy Scan button connector
        """
        self.ScanThread_Starter()
    
    def scanHard(self):
        """
        Hard Scan button connector
        """
        # Set correct max for progress bar
        self.ScanThread_Starter(scan_type=1)

    def ScanThread_Starter(self, scan_type=0):
        """
        Scan Thread Starter
        """
        self.stopLagSwitch()
        self.stopDupe(log=False)
        self.stopPercentCut(log=False)
        if not self.connected(show_msg_box=True):
            return

        self.centralwidget.setEnabled(False)
        
        # Save copy of killed devices
        self.killer.store()
        
        _pre_scan_ips = [v.get('ip') for v in self.killer.killed.values() if v.get('ip')]
        self.killer.unkill_all()
        for _ip in _pre_scan_ips:
            try:
                unblock_ip(_ip)
            except Exception:
                pass
        
        self.log(
            ['Arping', 'Pinging'][scan_type] + ' your network...',
            [UI_LOG_RESTORE_FG, UI_LOG_VICTIM_BLOCK_FG][scan_type],
        )
        
        self.pgbar.setVisible(True)
        if self.taskbar_progress:
            self.taskbar_progress.setVisible(True)
        self.pgbar.setMaximum(self.scanner.device_count)
        if self.taskbar_progress:
            self.taskbar_progress.setMaximum(self.scanner.device_count)
        self.pgbar.setValue(self.scanner.device_count * (not scan_type))
        
        self.scan_thread.scanner = self.scanner
        self.scan_thread.scan_type = scan_type
        self.scan_thread.start()

    def ScanThread_Reciever(self):
        """
        Scan Thread results reciever
        """
        self.centralwidget.setEnabled(True)
        self.pgbar.setVisible(False)
        if self.taskbar_progress:
            self.taskbar_progress.setVisible(False)
        self.processDevices()
    
    def UpdateThread_Starter(self):
        """
        Periodic HEAD polling refreshes the settings update badge (gear hint).
        Installing builds is only from Settings → Install Latest Build.
        """
        self._start_periodic_update_availability_poll()

    def UpdateThread_Reciever(self):
        """
        Legacy hook from upstream; unused.
        """
        pass

    def _should_poll_update_availability(self):
        import sys

        if not getattr(sys, 'frozen', False) or not sys.platform.startswith('win'):
            return False
        if not (APP_BUILD_TIME_ISO or '').strip():
            return False
        try:
            from tools.updater_core import selected_update_url

            return bool(selected_update_url())
        except Exception:
            return False

    def _start_periodic_update_availability_poll(self):
        if not self._should_poll_update_availability():
            return
        self._update_poll_timer = QTimer(self)
        self._update_poll_timer.setInterval(_UPDATE_POLL_INTERVAL_MS)
        self._update_poll_timer.timeout.connect(self._poll_remote_update_status_foreground)
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state_for_update_poll)
        self._sync_update_poll_timer_for_app_state()
        QTimer.singleShot(8000, self._poll_remote_update_status_if_active)

        self._update_daily_poll_timer = QTimer(self)
        self._update_daily_poll_timer.setInterval(_UPDATE_POLL_DAILY_MS)
        self._update_daily_poll_timer.timeout.connect(self._poll_remote_update_status_daily)
        self._update_daily_poll_timer.start()

    def _should_run_update_poll_now(self):
        """Only hit the network while ZubCut is the active (foreground) application."""
        app = QApplication.instance()
        if app is None:
            return False
        return app.applicationState() == Qt.ApplicationActive

    def _sync_update_poll_timer_for_app_state(self):
        t = getattr(self, '_update_poll_timer', None)
        if t is None or not self._should_poll_update_availability():
            return
        if self._should_run_update_poll_now():
            if not t.isActive():
                t.start()
        else:
            t.stop()

    def _on_app_state_for_update_poll(self, state):
        self._sync_update_poll_timer_for_app_state()
        if state == Qt.ApplicationActive and self._should_poll_update_availability():
            QTimer.singleShot(400, self._poll_remote_update_status_if_active)

    def _poll_remote_update_status_if_active(self):
        if not self._should_run_update_poll_now():
            return
        self._poll_remote_update_status_foreground()

    def _poll_remote_update_status_foreground(self):
        self._poll_remote_update_status(require_foreground=True)

    def _poll_remote_update_status_daily(self):
        self._poll_remote_update_status(require_foreground=False)

    def _update_status_poll_thread_is_running(self):
        """True if a poll worker is still alive and running (guards deleted C++ wrapper)."""
        th = getattr(self, '_update_status_poll_thread', None)
        if th is None:
            return False
        try:
            return th.isRunning()
        except RuntimeError:
            # deleteLater already ran; clear stale Python reference.
            self._update_status_poll_thread = None
            return False

    def _on_update_status_poll_thread_finished(self):
        th = self.sender()
        if th is getattr(self, '_update_status_poll_thread', None):
            self._update_status_poll_thread = None

    def _poll_remote_update_status(self, require_foreground=True):
        if not self._should_poll_update_availability():
            return
        if require_foreground and not self._should_run_update_poll_now():
            return
        if self._update_status_poll_thread_is_running():
            return
        # No parent: parenting QThread to the main window has caused lifetime/native issues on Windows.
        poll = _UpdateStatusPollThread()
        self._update_status_poll_thread = poll
        poll.done.connect(
            self._on_update_status_polled,
            type=Qt.QueuedConnection,
        )
        poll.finished.connect(self._on_update_status_poll_thread_finished)
        poll.finished.connect(poll.deleteLater)
        poll.start()

    def _on_update_status_polled(self, available, published_label):
        try:
            sw = getattr(self, 'settings_window', None)
            if sw is not None:
                sw.apply_update_banner_state(available, published_label)
            # Defer gear stylesheet off the signal stack (less re-entrancy with frameless chrome).
            QTimer.singleShot(0, self._sync_settings_gear_update_hint)
        except Exception:
            pass

    def _sync_settings_gear_update_hint(self):
        try:
            if getattr(self.settings_window, '_update_available', False):
                self.btnSettings.setStyleSheet(_SETTINGS_BTN_UPDATE_STYLE)
                self.btnSettings.setToolTip(
                    _SETTINGS_BTN_TIP
                    + ' — New build available; open Settings to download and install.'
                )
            else:
                self.btnSettings.setStyleSheet(self.BUTTON_NORMAL_STYLE)
                self.btnSettings.setToolTip(_SETTINGS_BTN_TIP)
        except Exception:
            pass
    
    def _main_window_is_foreground(self):
        aw = QApplication.activeWindow()
        return aw is not None and aw is self

    def _app_window_is_foreground(self):
        app_windows = [
            self,
            getattr(self, 'settings_window', None),
            getattr(self, 'about_window', None),
            getattr(self, 'device_window', None),
            getattr(self, 'traffic_window', None),
        ]
        aw = QApplication.activeWindow()
        if any(w is not None and aw is w for w in app_windows):
            return True
        # Frameless/top-level dialog focus on Windows can sometimes report no activeWindow
        # (or not the expected top-level). Fall back to focused widget ownership.
        fw = QApplication.focusWidget()
        if fw is None:
            return False
        top = fw.window()
        return any(w is not None and top is w for w in app_windows)

    def _shortcut_scan_easy(self):
        if not self._main_window_is_foreground():
            return
        if self.btnScanEasy.isEnabled():
            self.scanEasy()

    def refresh_keyboard_shortcuts_from_settings(self):
        """Apply keybind settings to global shortcuts and tooltips."""
        s = import_settings()
        k_kill = keyseq_from_setting(s.get('key_kill'), Qt.Key_L)
        k_lag = keyseq_from_setting(s.get('key_lag'), Qt.Key_M)
        k_dupe = keyseq_from_setting(s.get('key_dupe'), Qt.Key_P)
        k_pct = keyseq_from_setting(s.get('key_pctcut'), Qt.Key_K)
        self._shortcut_kill_l.setKey(k_kill)
        self._shortcut_kill_l.setAutoRepeat(False)
        self._shortcut_lag_global.setKey(k_lag)
        self._shortcut_lag_global.setAutoRepeat(False)
        self._shortcut_dupe_global.setKey(k_dupe)
        self._shortcut_dupe_global.setAutoRepeat(False)
        self._shortcut_pctcut_global.setKey(k_pct)
        self._shortcut_pctcut_global.setAutoRepeat(False)
        nk = k_kill.toString(QKeySequence.NativeText)
        nl = k_lag.toString(QKeySequence.NativeText)
        np = k_dupe.toString(QKeySequence.NativeText)
        nk_pct = k_pct.toString(QKeySequence.NativeText)
        self._shortcut_label_kill = nk or 'L'
        self._shortcut_label_lag = nl or 'M'
        self._shortcut_label_dupe = np or 'P'
        self._shortcut_label_pctcut = nk_pct or 'K'
        self._btn_kill_tooltip_static = (
            'Kill toggle — Turn blocking on or off for the selected device. '
            'Shortcut: %s (only while the main ZubCut window is the active window).' % nk
        )
        self.btnKill.setToolTip(self._btn_kill_tooltip_static)
        self.btnLagSwitch.setToolTip(
            'Lag Switch — start/stop intermittent blocking for selected device. '
            'Controls below set timing and direction. Shortcut: %s.'
            % nl
        )
        self.btnDupe.setToolTip(
            'Dupe — one-shot lag for selected duration, then full stop. '
            'Controls below set duration and direction. Shortcut: %s.' % np
        )
        self.btnPercentCut.setToolTip(
            'Percent Cut toggle — percentage-based cut on selected device. '
            'Shortcut: %s (main app window in foreground).' % nk_pct
        )
        self._updateKillButtonState()
        self._updateLagSwitchButtonState()
        self._updateDupeButtonState()
        self._updatePercentCutButtonState()

    def _shortcut_main_l(self):
        """Kill toggle when any app window is foreground, using configured shortcut."""
        if not self._app_window_is_foreground():
            return
        if _focus_widget_absorbs_letter_key(QApplication.focusWidget()):
            return
        # Same handler as btnKill.clicked — do not gate on btnKill.isEnabled(); toggleKill
        # enforces connected(), selection, and admin the same for mouse and keyboard.
        self.toggleKill('shortcut_key')

    def _shortcut_global_lag(self):
        """Lag toggle while app is foreground, regardless of active sub-window."""
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
        if not self.tableScan.selectedItems():
            self.log('No device selected', 'red')
            return
        device = self.current_index()
        if device['admin']:
            self.log('Cannot lag admin device', UI_LOG_VICTIM_BLOCK_FG)
            return
        if self._toggle_start_blocked('lag'):
            return
        lag_edge = 'start'
        if self._ignore_duplicate_toggle_edge('lag', device['mac'], lag_edge):
            return
        lag_ms, normal_ms, direction = self._lag_inline_values()
        self.applyLagSwitchSettings(lag_ms, normal_ms, direction)
        self.startLagSwitch(device)

    def _shortcut_global_dupe(self):
        """Dupe toggle while app is foreground, regardless of active sub-window."""
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
        if not self.tableScan.selectedItems():
            self.log('No device selected', 'red')
            return
        device = self.current_index()
        if device['admin']:
            self.log('Cannot dupe admin device', UI_LOG_VICTIM_BLOCK_FG)
            return
        if self._toggle_start_blocked('dupe'):
            return
        dupe_edge = 'start'
        if self._ignore_duplicate_toggle_edge('dupe', device['mac'], dupe_edge):
            return
        ms, direction = self._dupe_inline_values()
        self.dupe_duration_ms = ms
        self.dupe_direction = direction
        self.startDupe(device, self.dupe_duration_ms, self.dupe_direction)

    def _shortcut_global_pctcut(self):
        if not self._app_window_is_foreground():
            return
        if _focus_widget_absorbs_letter_key(QApplication.focusWidget()):
            return
        self.togglePercentCut('shortcut_key')

    def applyLagSwitchSettings(self, block_ms, release_ms, direction):
        self.lag_block_ms = block_ms
        self.lag_release_ms = release_ms
        self.lag_direction = direction

    def _refresh_lag_timing_from_dialog(self):
        """Keep lag settings in sync with always-visible inline controls."""
        try:
            lag_ms, normal_ms, direction = self._lag_inline_values()
            self.applyLagSwitchSettings(lag_ms, normal_ms, direction)
        except Exception:
            pass

    def _direction_from_checks(self, both_cb, in_cb, out_cb):
        if in_cb.isChecked() and not out_cb.isChecked():
            return 'in'
        if out_cb.isChecked() and not in_cb.isChecked():
            return 'out'
        return 'both'

    def _lag_inline_values(self):
        return self.lagSpinMain.value(), self.normalSpinMain.value(), self._direction_from_checks(
            self.lagDirBoth, self.lagDirIncoming, self.lagDirOutgoing
        )

    def _dupe_inline_values(self):
        return self.dupeSpinMain.value(), self._direction_from_checks(
            self.dupeDirBoth, self.dupeDirIncoming, self.dupeDirOutgoing
        )

    def _sync_inline_flow_controls_enabled(self):
        lag_locked = bool(self.lag_active and self.lag_device_mac)
        self.lagDirBoth.setEnabled(not lag_locked)
        self.lagDirIncoming.setEnabled(not lag_locked)
        self.lagDirOutgoing.setEnabled(not lag_locked)
        dupe_locked = bool(self.dupe_active and self.dupe_device_mac)
        self.dupeDirBoth.setEnabled(not dupe_locked)
        self.dupeDirIncoming.setEnabled(not dupe_locked)
        self.dupeDirOutgoing.setEnabled(not dupe_locked)

    def _apply_inline_panel_styles(self):
        sel_bg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_BG', '#316E69')
        admin_bg = getattr(_zcut_constants, 'ADMIN_DEVICE_TABLE_ROW_BG', '#5D706E')
        sel_fg = getattr(_zcut_constants, 'UI_TABLE_SELECTION_FG', '#f2f2f2')
        panel_bg = '#141414'
        field_bg = '#141414'
        panel_style = (
            'QGroupBox#groupLagInline, QGroupBox#groupDupeInline {'
            f' border: 1px solid {sel_bg}; border-radius: 6px; margin-top: 8px;'
            f' padding-top: 8px; background-color: {panel_bg}; }}'
            'QGroupBox#groupLagInline::title, QGroupBox#groupDupeInline::title {'
            f' subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {admin_bg}; font-weight: bold; }}'
            'QGroupBox#groupLagInline QWidget, QGroupBox#groupDupeInline QWidget { background-color: transparent; }'
            f'QGroupBox#groupLagInline QLabel, QGroupBox#groupDupeInline QLabel {{ color: {admin_bg}; background-color: transparent; }}'
            f'QGroupBox#groupLagInline QCheckBox, QGroupBox#groupDupeInline QCheckBox {{ color: {admin_bg}; background-color: transparent; }}'
            f'QGroupBox#groupLagInline QCheckBox:hover, QGroupBox#groupDupeInline QCheckBox:hover {{ color: {sel_bg}; background-color: transparent; }}'
            f'QGroupBox#groupLagInline QCheckBox::indicator, QGroupBox#groupDupeInline QCheckBox::indicator {{'
            f' image: none; width: 14px; height: 14px; border: 1px solid {admin_bg}; background-color: transparent; margin: 0px; }}'
            f'QGroupBox#groupLagInline QCheckBox::indicator:unchecked, QGroupBox#groupDupeInline QCheckBox::indicator:unchecked {{'
            f' image: none; border: 1px solid {admin_bg}; background-color: transparent; }}'
            f'QGroupBox#groupLagInline QCheckBox::indicator:hover, QGroupBox#groupDupeInline QCheckBox::indicator:hover {{'
            f' image: none; border: 1px solid {sel_bg}; background-color: transparent; }}'
            f'QGroupBox#groupLagInline QCheckBox::indicator:unchecked:hover, QGroupBox#groupDupeInline QCheckBox::indicator:unchecked:hover {{'
            f' image: none; border: 1px solid {sel_bg}; background-color: transparent; }}'
            f'QGroupBox#groupLagInline QCheckBox::indicator:checked, QGroupBox#groupDupeInline QCheckBox::indicator:checked {{'
            f' image: none; background-color: {sel_bg}; border: 1px solid {admin_bg}; }}'
            'QGroupBox#groupLagInline QSpinBox, QGroupBox#groupDupeInline QSpinBox {'
            f' min-height: 24px; border: 1px solid {admin_bg}; border-radius: 4px;'
            f' padding: 2px 6px; background-color: {field_bg}; color: {admin_bg}; }}'
            'QGroupBox#groupLagInline QSpinBox::up-button, QGroupBox#groupLagInline QSpinBox::down-button,'
            'QGroupBox#groupDupeInline QSpinBox::up-button, QGroupBox#groupDupeInline QSpinBox::down-button {'
            f' background-color: {panel_bg}; border: 1px solid {admin_bg}; width: 16px; }}'
            'QGroupBox#groupLagInline QSpinBox::up-button:hover, QGroupBox#groupLagInline QSpinBox::down-button:hover,'
            'QGroupBox#groupDupeInline QSpinBox::up-button:hover, QGroupBox#groupDupeInline QSpinBox::down-button:hover {'
            f' background-color: {sel_bg}; border: 1px solid {sel_bg}; }}'
            'QGroupBox#groupLagInline QSpinBox::up-arrow, QGroupBox#groupDupeInline QSpinBox::up-arrow {'
            ' image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiM5YTlhOWEiIGQ9Ik0wIDYgTDQuNSAwIEw5IDYgWiIvPjwvc3ZnPg==);'
            ' border: none; width: 9px; height: 6px; margin: 0 1px 1px 1px; }'
            'QGroupBox#groupLagInline QSpinBox::down-arrow, QGroupBox#groupDupeInline QSpinBox::down-arrow {'
            ' image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiM5YTlhOWEiIGQ9Ik0wIDAgTDQuNSA2IEw5IDAgWiIvPjwvc3ZnPg==);'
            ' border: none; width: 9px; height: 6px; margin: 1px 1px 0 1px; }'
            f'QLabel#lblDupeCountdownMain {{ color: {sel_bg}; font-weight: bold; }}'
        )
        self.groupLagInline.setStyleSheet(panel_style)
        self.groupDupeInline.setStyleSheet(panel_style)
        percent_style = (
            f'QLabel#lblPercentCut {{ color: {admin_bg}; background-color: transparent; }}'
            f'QSpinBox#spinPercentCutMain {{'
            f' border: 1px solid {admin_bg}; border-radius: 4px;'
            f' padding: 2px 6px; background-color: {field_bg}; color: {admin_bg}; }}'
            f'QSpinBox#spinPercentCutMain::up-button, QSpinBox#spinPercentCutMain::down-button {{'
            f' background-color: {panel_bg}; border: 1px solid {admin_bg}; width: 16px; }}'
            f'QSpinBox#spinPercentCutMain::up-button:hover, QSpinBox#spinPercentCutMain::down-button:hover {{'
            f' background-color: {sel_bg}; border: 1px solid {sel_bg}; }}'
            'QSpinBox#spinPercentCutMain::up-arrow {'
            ' image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiM5YTlhOWEiIGQ9Ik0wIDYgTDQuNSAwIEw5IDYgWiIvPjwvc3ZnPg==);'
            ' border: none; width: 9px; height: 6px; margin: 0 1px 1px 1px; }'
            'QSpinBox#spinPercentCutMain::down-arrow {'
            ' image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5IiBoZWlnaHQ9IjYiPjxwYXRoIGZpbGw9IiM5YTlhOWEiIGQ9Ik0wIDAgTDQuNSA2IEw5IDAgWiIvPjwvc3ZnPg==);'
            ' border: none; width: 9px; height: 6px; margin: 1px 1px 0 1px; }'
            'QSlider#sliderPercentCutMain { background-color: transparent; }'
            f'QSlider#sliderPercentCutMain::groove:horizontal {{'
            f' background-color: {field_bg}; height: 4px; border-radius: 2px; }}'
            f'QSlider#sliderPercentCutMain::sub-page:horizontal {{'
            f' background-color: {sel_bg}; height: 4px; border-radius: 2px; }}'
            f'QSlider#sliderPercentCutMain::add-page:horizontal {{'
            f' background-color: {panel_bg}; height: 4px; border-radius: 2px; }}'
        )
        self.lblPercentCut.setStyleSheet(percent_style)
        self.sliderPercentCutMain.setStyleSheet(percent_style)
        self.spinPercentCutMain.setStyleSheet(percent_style)

    def startLagSwitch(self, device):
        if self._toggle_start_blocked('lag'):
            return
        self.stopDupe(refresh_dialog=True, log=False)
        if self.lag_active:
            self.stopLagSwitch(refresh_dialog=False)
        self.lag_device_mac = device['mac']
        self._lag_device_snapshot = dict(device)
        self.lag_active = True
        self._refresh_lag_timing_from_dialog()
        self.btnLagSwitch.setText('■ LAGGING')
        self.btnLagSwitch.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        dir_text = {'both': 'all', 'in': 'incoming', 'out': 'outgoing'}[self.lag_direction]
        self.log(
            f'Lag switch ON: {self.lag_block_ms}ms lag ({dir_text}) / {self.lag_release_ms}ms normal',
            UI_LOG_VICTIM_BLOCK_FG,
        )
        self._lag_apply_block(device)
        self._schedule_lag_start_reassert(device['mac'])
        self._lag_in_allow_phase = False
        self.lag_timer.start(max(1, int(self.lag_block_ms)))
        self._refresh_flow_toggle_ui()
        self._repaint_all_table_rows_for_hover()

    def _schedule_lag_start_reassert(self, mac):
        """Quick ON reasserts so lag takes effect immediately despite ARP/firewall race timing."""
        def _reassert():
            if not self.lag_active or self.lag_device_mac != mac or self._lag_in_allow_phase:
                return
            dev = self._get_device_by_mac(mac) or self._victim_record_for_mac(mac)
            if not dev:
                return
            try:
                self._lag_apply_block(dev)
            except Exception:
                pass

        QTimer.singleShot(120, _reassert)
        QTimer.singleShot(320, _reassert)

    def _refresh_table_row_for_mac(self, mac):
        """Update table row colors for one MAC without rebuilding the whole table."""
        if not mac:
            return
        for row, d in enumerate(self.scanner.devices):
            if d['mac'] == mac:
                self.fillTableRow(row, d)
                self._repaint_table_row_for_hover(row)
                break

    def _ensure_network_context_for_victim(self, device) -> bool:
        """
        Bind scanner + killer to the NIC that routes to the victim (e.g. hotspot vs Ethernet).
        Does not persist Settings; runtime only so ARP/firewall use the correct adapter.
        """
        if not device or not device.get('ip'):
            return False
        try:
            changed = self.scanner.sync_iface_for_victim_ip(device['ip'])
        except Exception:
            return False
        if not changed:
            return False
        self.killer.iface = self.scanner.iface
        self.killer.router = self.scanner.router
        self.killer._close_socket()
        try:
            from scapy.all import conf as scapy_conf

            guid = self.scanner.iface.guid if self.scanner.iface else None
            if guid:
                scapy_conf.iface = guid
        except Exception:
            pass
        label = (getattr(self.scanner.iface, 'name', None) or '').strip() or getattr(
            self.scanner.iface, 'guid', ''
        )
        try:
            # Persist auto-selected adapter so Settings reflects the active runtime NIC.
            iface_name = getattr(self.scanner.iface, 'name', None) or ''
            if iface_name:
                set_settings('iface', iface_name)
                sw = getattr(self, 'settings_window', None)
                combo = getattr(sw, 'comboInterface', None) if sw is not None else None
                if combo is not None:
                    idx = combo.findData(iface_name)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
        except Exception:
            pass
        self.log(
            f'Using network adapter for {device["ip"]}: {label}',
            UI_LOG_RESTORE_FG,
        )
        return True

    def _apply_victim_block(self, device, direction):
        self._ensure_network_context_for_victim(device)
        self.killer.disable_percent_cut(device['mac'])
        if device['mac'] not in self.killer.killed:
            self.killer.kill(device)
        iface = self.scanner.iface.name if self.scanner.iface else 'en0'
        block_ip(iface, device['ip'], direction)
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(device['mac'])
        self._updateKillButtonState()

    def _clear_victim_block(self, device):
        self._ensure_network_context_for_victim(device)
        try:
            unblock_ip(device['ip'])
        except Exception:
            pass
        if device['mac'] in self.killer.killed:
            try:
                victim = self._victim_record_for_mac(device['mac']) or device
                self.killer.unkill(victim)
            except Exception:
                pass
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(device['mac'])
        self._updateKillButtonState()

    def _lag_enter_allow_phase(self, device):
        """
        Allow window (bottom spin): drop firewall rules and stop ARP spoof for this victim.
        If we only removed firewall rules while still MITM'd, traffic would still flow through
        this PC — and on Windows IP forwarding is often off, so the victim stays broken.
        """
        try:
            self._clear_victim_block(device)
        except Exception:
            pass

    def _lag_apply_block(self, device):
        self._apply_victim_block(device, self.lag_direction)

    def _lag_phase_tick(self):
        if not self.lag_active:
            return
        self._refresh_lag_timing_from_dialog()
        device = self._get_device_by_mac(self.lag_device_mac)
        if not device:
            self.stopLagSwitch()
            return
        block_ms = max(1, int(self.lag_block_ms))
        allow_ms = max(25, int(self.lag_release_ms))

        if not self._lag_in_allow_phase:
            # Block interval (top spin) just finished -> allow traffic for bottom spin duration.
            try:
                self._lag_enter_allow_phase(device)
            except Exception:
                pass
            self._lag_in_allow_phase = True
            next_ms = allow_ms
        else:
            # Allow interval (bottom spin) just finished -> block again for top spin duration.
            try:
                self._lag_apply_block(device)
            except Exception:
                pass
            self._lag_in_allow_phase = False
            next_ms = block_ms

        if self.lag_active:
            self.lag_timer.start(next_ms)

    def stopLagSwitch(self, refresh_dialog=True):
        if not self.lag_active:
            return
        prev_mac = self.lag_device_mac
        # Tear down active state first so any concurrent timer tick becomes a no-op.
        self.lag_active = False
        self.lag_device_mac = None
        self._lag_in_allow_phase = False
        self.lag_timer.stop()
        snap = getattr(self, '_lag_device_snapshot', None)
        self._lag_device_snapshot = None
        device = self._get_device_by_mac(prev_mac)
        if not device and snap and snap.get('mac') == prev_mac:
            device = snap
        if device and device.get('mac') == prev_mac:
            # During the "normal" phase the victim is already unkill()'d; we still must enforce
            # teardown here so MITM/ARP cannot stick after the UI shows OFF (same idea as Kill OFF).
            victim = self._victim_record_for_mac(prev_mac) or device
            if victim:
                try:
                    self._ensure_network_context_for_victim(victim)
                except Exception:
                    pass
            try:
                unblock_ip(device['ip'])
            except Exception:
                pass
            if victim:
                try:
                    self.killer.unkill(victim)
                    self.killer.reinforce_restore(victim)
                    lag_off_seq = self._bump_flow_off_intent('lag', prev_mac)
                    self._schedule_flow_off_reinforce('lag', prev_mac, lag_off_seq, 60, victim)
                    self._schedule_flow_off_reinforce('lag', prev_mac, lag_off_seq, 180, victim)
                except Exception:
                    pass
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

    def startDupe(self, device, duration_ms, direction):
        if self._toggle_start_blocked('dupe'):
            return
        self.stopLagSwitch(refresh_dialog=True)
        self.stopDupe(refresh_dialog=False, log=False)
        self.dupe_device_mac = device['mac']
        self.dupe_active = True
        self.dupe_direction = direction
        self.dupe_duration_ms = duration_ms
        self._apply_victim_block(device, direction)
        self.btnDupe.setText('■ DUPE')
        self.btnDupe.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        dir_text = {'both': 'all', 'in': 'incoming', 'out': 'outgoing'}[direction]
        self.log(f'Dupe: {duration_ms}ms ({dir_text}), then full stop', UI_LOG_VICTIM_BLOCK_FG)
        self._dupe_elapsed.start()
        self.dupe_timer.start(max(1, int(duration_ms)))
        self._dupe_countdown_timer.start()
        self._tick_dupe_countdown()
        self._refresh_flow_toggle_ui()
        self._repaint_all_table_rows_for_hover()

    def dupe_remaining_ms(self):
        if not self.dupe_active:
            return None
        return max(0, int(self.dupe_duration_ms - self._dupe_elapsed.elapsed()))

    def _tick_dupe_countdown(self):
        if not self.dupe_active:
            self._dupe_countdown_timer.stop()
            self.lblDupeCountdownMain.setVisible(False)
            self.lblDupeCountdownMain.setText('')
            return
        rem = self.dupe_remaining_ms()
        # Finish as soon as elapsed time says so; avoids showing "0.0 s" until the
        # coarse single-shot dupe_timer fires (can lag tens–100+ ms behind).
        if rem is not None and rem <= 0:
            self._dupe_countdown_timer.stop()
            self.stopDupe(log_message='Dupe finished')
            return
        if rem is None or rem <= 0:
            self.lblDupeCountdownMain.setVisible(False)
            self.lblDupeCountdownMain.setText('')
        else:
            sec = rem / 1000.0
            self.lblDupeCountdownMain.setVisible(True)
            if sec >= 60:
                whole = int(sec)
                m, s = divmod(whole, 60)
                self.lblDupeCountdownMain.setText(f'Time left: {m}:{s:02d}')
            else:
                self.lblDupeCountdownMain.setText(f'Time left: {sec:.1f} s')

    def _dupe_timer_fired(self):
        self.stopDupe(log_message='Dupe finished')

    def stopDupe(self, refresh_dialog=True, log=True, log_message='Dupe stopped'):
        if not self.dupe_active:
            return
        prev_mac = self.dupe_device_mac
        # Mark inactive first to prevent re-entrant timer paths from reapplying state.
        self.dupe_active = False
        self.dupe_device_mac = None
        self._dupe_countdown_timer.stop()
        self.dupe_timer.stop()
        self.lblDupeCountdownMain.setVisible(False)
        self.lblDupeCountdownMain.setText('')
        device = self._get_device_by_mac(prev_mac)
        if device:
            try:
                self._clear_victim_block(device)
                dupe_off_seq = self._bump_flow_off_intent('dupe', prev_mac)
                self._schedule_flow_off_reinforce('dupe', prev_mac, dupe_off_seq, 60, device)
                self._schedule_flow_off_reinforce('dupe', prev_mac, dupe_off_seq, 180, device)
            except Exception:
                pass
        self.btnDupe.setText('Dupe')
        self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        if log:
            self.log(log_message, UI_LOG_RESTORE_FG)
        if refresh_dialog:
            self._refresh_flow_toggle_ui()
        else:
            self._updateDupeButtonState()
            self._updateKillButtonState()
        self._repaint_all_table_rows_for_hover()

    def _updateDupeButtonState(self):
        if self.dupe_active and self.dupe_device_mac:
            key = getattr(self, '_shortcut_label_dupe', 'P')
            self.btnDupe.setText(f'■ DUPE (Press {key} to turn off)')
            self.btnDupe.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnDupe.setText('Dupe')
            self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self._sync_inline_flow_controls_enabled()

    def _updatePercentCutButtonState(self):
        pct = self._clamp_percent(self.spinPercentCutMain.value())
        key = getattr(self, '_shortcut_label_pctcut', 'K')
        if self.percent_cut_active and self.percent_cut_device_mac:
            self.btnPercentCut.setText(f'■ CUT {pct}% (Press {key} to turn off)')
            self.btnPercentCut.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnPercentCut.setText(f'Percent Cut: {pct}%')
            self.btnPercentCut.setStyleSheet(self.BUTTON_NORMAL_STYLE)

    def _refresh_flow_toggle_ui(self):
        """Synchronize Lag/Dupe/Kill button text after cross-flow toggles."""
        self._updateLagSwitchButtonState()
        self._updateDupeButtonState()
        self._updateKillButtonState()
        self._updatePercentCutButtonState()
        self._sync_inline_flow_controls_enabled()

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
            dev = self._get_device_by_mac(self.percent_cut_device_mac) or self._victim_record_for_mac(self.percent_cut_device_mac)
            if dev:
                allow_pct = max(0, 100 - pct)
                try:
                    self._ensure_network_context_for_victim(dev)
                    self.killer.apply_percent_cut(dev, pass_percent=allow_pct, direction='both')
                except Exception:
                    pass
        self._updatePercentCutButtonState()

    def _ignore_duplicate_toggle_edge(self, kind: str, mac: str | None, edge: str) -> bool:
        """
        Ignore a second identical edge (same MAC, same activate/stop/…) within a few
        ms — filters duplicate clicks / key deliveries. Alternating on/off is not delayed.
        Held keys: use QShortcut.setAutoRepeat(False).
        """
        if not mac:
            return False
        now = time.monotonic()
        mac_attr = f'_{kind}_edge_debounce_mac'
        edge_attr = f'_{kind}_edge_debounce_edge'
        until_attr = f'_{kind}_edge_debounce_until'
        if (
            mac == getattr(self, mac_attr, None)
            and edge == getattr(self, edge_attr, None)
            and now < getattr(self, until_attr, 0.0)
        ):
            return True
        setattr(self, mac_attr, mac)
        setattr(self, edge_attr, edge)
        setattr(self, until_attr, now + 0.03)
        return False

    def _has_explicit_kill_active(self):
        return any(bool(v) for v in self.killed_devices.values())

    @staticmethod
    def _toggle_kind_label(kind):
        return {'kill': 'Kill', 'lag': 'Lag Switch', 'dupe': 'Dupe', 'pctcut': 'Percent Cut'}.get(kind, kind)

    def _active_toggle_kind(self):
        if self.lag_active and self.lag_device_mac:
            return 'lag'
        if self.dupe_active and self.dupe_device_mac:
            return 'dupe'
        if self.percent_cut_active and self.percent_cut_device_mac:
            return 'pctcut'
        if self._has_explicit_kill_active():
            return 'kill'
        return None

    def _toggle_start_blocked(self, requested_kind):
        active_kind = self._active_toggle_kind()
        if active_kind and active_kind != requested_kind:
            self.log(
                f'{self._toggle_kind_label(active_kind)} is active. Turn it off first.',
                UI_LOG_VICTIM_BLOCK_FG,
            )
            return True
        return False

    def toggleKill(self, source='unknown'):
        if not self.connected():
            return
        device = self._get_selected_device()
        if not device:
            self.log('No device selected', 'red')
            return
        if device['admin']:
            self.log('Cannot kill admin device', UI_LOG_VICTIM_BLOCK_FG)
            return

        mac = device['mac']
        current_ui_on = bool(self.killed_devices.get(mac, mac in self.killer.killed))
        next_state = not current_ui_on
        if next_state and self._toggle_start_blocked('kill'):
            return
        self.killed_devices[mac] = next_state
        self._updateKillButtonState()
        self._run_kill_command(mac, device, turn_on=next_state, source=source)

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

        mac = device['mac']
        turning_on = not (self.percent_cut_active and self.percent_cut_device_mac == mac)
        if turning_on and self._toggle_start_blocked('pctcut'):
            return

        if turning_on:
            if self.percent_cut_active and self.percent_cut_device_mac and self.percent_cut_device_mac != mac:
                self.stopPercentCut(log=False)
            if self.lag_active and self.lag_device_mac == mac:
                self.stopLagSwitch(refresh_dialog=True)
            if self.dupe_active and self.dupe_device_mac == mac:
                self.stopDupe(log=False)
            if self._kill_ui_shows_on(mac):
                self._run_kill_command(mac, device, turn_on=False, source='pctcut_auto_off_kill')
            pct = self._clamp_percent(self.spinPercentCutMain.value())
            allow_pct = max(0, 100 - pct)
            self._ensure_network_context_for_victim(device)
            self.killer.apply_percent_cut(device, pass_percent=allow_pct, direction='both')
            self.percent_cut_active = True
            self.percent_cut_device_mac = mac
            self.log(
                f'Percent Cut ON for {device["ip"]}: {pct}% cut ({allow_pct}% allowed)',
                UI_LOG_VICTIM_BLOCK_FG,
            )
            self._refresh_flow_toggle_ui()
            self.showDevices()
            return

        self.stopPercentCut(log=True)

    def stopPercentCut(self, log=True):
        if not self.percent_cut_active:
            return
        prev_mac = self.percent_cut_device_mac
        self.percent_cut_active = False
        self.percent_cut_device_mac = None
        victim = self._victim_record_for_mac(prev_mac) or self._get_device_by_mac(prev_mac)
        if victim:
            try:
                self._ensure_network_context_for_victim(victim)
                self.killer.disable_percent_cut(prev_mac)
                self.killer.unkill(victim)
                self.killer.reinforce_restore(victim)
                pct_off_seq = self._bump_flow_off_intent('pctcut', prev_mac)
                self._schedule_flow_off_reinforce('pctcut', prev_mac, pct_off_seq, 60, victim)
                self._schedule_flow_off_reinforce('pctcut', prev_mac, pct_off_seq, 180, victim)
                self._schedule_flow_off_reinforce('pctcut', prev_mac, pct_off_seq, 350, victim)
            except Exception:
                pass
        if log and victim:
            self.log('Percent Cut OFF for ' + victim['ip'], UI_LOG_RESTORE_FG)
        self._refresh_flow_toggle_ui()
        self.showDevices()

    def _run_kill_command(self, mac, device, turn_on, source='unknown'):
        """Immediate explicit command path: one click => one kill/unkill command."""
        snapshot_map = getattr(self, '_kill_device_snapshot', None)
        if snapshot_map is None:
            snapshot_map = {}
            self._kill_device_snapshot = snapshot_map
        snapshot_map[mac] = dict(device)
        actual_on = mac in self.killer.killed
        next_seq = int(self._kill_intent_seq.get(mac, 0)) + 1
        self._kill_intent_seq[mac] = next_seq
        if device:
            self._ensure_network_context_for_victim(device)
        if turn_on:
            if self.lag_active and self.lag_device_mac == mac:
                self.stopLagSwitch(refresh_dialog=True)
            if self.dupe_active and self.dupe_device_mac == mac:
                self.stopDupe(log=False)
            if self.percent_cut_active and self.percent_cut_device_mac == mac:
                self.stopPercentCut(log=False)
            if not actual_on and device:
                self.killer.disable_percent_cut(mac)
                self.killer.kill(device)
                try:
                    iface = self.scanner.iface.name if self.scanner.iface else 'en0'
                    block_ip(iface, device['ip'], 'both')
                except Exception:
                    pass
                self.log('Kill ON for ' + device['ip'], UI_LOG_VICTIM_BLOCK_FG)
        else:
            victim = self._victim_record_for_mac(mac) or device
            if victim:
                try:
                    unblock_ip(victim.get('ip') or '')
                except Exception:
                    pass
                self.killer.unkill(victim)
                self.killer.reinforce_restore(victim)
                if actual_on:
                    self.killer.reinforce_restore(victim)
                self.log('Kill OFF for ' + victim['ip'], UI_LOG_RESTORE_FG)
                # OFF-only delayed reinforcement; guarded by intent_seq so stale callbacks no-op.
                self._schedule_kill_off_reinforce(mac, next_seq, 60)
                self._schedule_kill_off_reinforce(mac, next_seq, 180)

        self.killed_devices[mac] = bool(turn_on)
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
        self._updateKillButtonState()
        self.showDevices()

    def _schedule_kill_off_reinforce(self, mac, intent_seq, delay_ms):
        """Delayed OFF reinforcement that self-cancels if intent changed."""
        def _cb():
            current_seq = int(self._kill_intent_seq.get(mac, 0))
            ui_on = bool(self.killed_devices.get(mac, False))
            if current_seq != int(intent_seq) or ui_on:
                return
            snapshot = (getattr(self, '_kill_device_snapshot', None) or {}).get(mac)
            victim = self._victim_record_for_mac(mac) or snapshot
            if not victim:
                return
            try:
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
            victim = self._victim_record_for_mac(mac) or device_snapshot
            if not victim:
                return
            try:
                self._ensure_network_context_for_victim(victim)
                self.killer.unkill(victim)
                self.killer.reinforce_restore(victim)
            except Exception:
                pass

        QTimer.singleShot(max(0, int(delay_ms)), _cb)

    def _kill_ui_shows_on(self, mac):
        """Kill button / bookkeeping: visual state is authoritative for toggle UX."""
        return bool(self.killed_devices.get(mac, mac in self.killer.killed))

    def _get_selected_device(self):
        if not self.tableScan.selectedItems():
            return None
        row = self.tableScan.currentRow()
        if row < 0 or row >= len(self.scanner.devices):
            return None
        return self.scanner.devices[row]

    def _sync_killed_devices(self):
        """
        Drop Kill-toggle bookkeeping when a MAC is no longer in killer.killed.
        Do not set True for every killer victim — lag/dupe also use killer.killed for ARP.
        """
        active_macs = set(self.killer.killed.keys())
        for mac in list(self.killed_devices.keys()):
            if mac not in active_macs:
                self.killed_devices[mac] = False

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

    def _updateKillButtonState(self):
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
        if self.lag_active and self.lag_device_mac == mac:
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
        if self.dupe_active and self.dupe_device_mac == mac:
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
        if base_tip:
            self.btnKill.setToolTip(base_tip)
        is_active = self._kill_ui_shows_on(mac)
        if is_active:
            kill_key = getattr(self, '_shortcut_label_kill', 'L')
            self._set_kill_button_active_look()
            self.btnKill.setText(f'■ KILL: ON\n(Press {kill_key} to turn off)')
            self.btnKill.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self._set_kill_button_idle_look()
            self.btnKill.setText('Kill: OFF')
            self.btnKill.setStyleSheet(self.BUTTON_NORMAL_STYLE)

    def _get_device_by_mac(self, mac):
        for device in self.scanner.devices:
            if device['mac'] == mac:
                return device
        return None

    def _victim_record_for_mac(self, mac):
        """
        Victim dict for unkill: same MAC as when killed, but IP refreshed from the current scan
        so ARP restore matches the real host after DHCP / rescan.
        """
        if mac not in self.killer.killed:
            return None
        victim = dict(self.killer.killed[mac])
        fresh = self._get_device_by_mac(mac)
        if fresh:
            victim['ip'] = fresh['ip']
        return victim

    def _enqueue_kill_off_only(self, mac, device):
        """After lag/dupe stop: execute an explicit OFF command immediately."""
        self.killed_devices[mac] = False
        self._updateKillButtonState()
        self._run_kill_command(mac, device, turn_on=False, source='enqueue_off_only')

