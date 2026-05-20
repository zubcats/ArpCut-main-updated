import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from pyperclip import copy

from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QMessageBox, \
                            QMenu, QSystemTrayIcon, QAction, QPushButton, \
                            QDialog, QFormLayout, QDialogButtonBox, QSpinBox, \
                            QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QGroupBox, \
                            QSizePolicy, QShortcut, QAbstractSpinBox, QAbstractItemView, QLineEdit, QSlider, \
                            QTextEdit, QPlainTextEdit, QWidget, QHeaderView, QFrame
from PyQt5.QtGui import QPixmap, QIcon, QFont, QKeySequence, QBrush, QFontMetrics
from PyQt5.QtCore import Qt, QObject, QTimer, QSize, QElapsedTimer, QThread, pyqtSignal, QEvent, pyqtSlot, QMetaObject, QEventLoop
try:
    from PyQt5.QtWinExtras import QWinTaskbarButton
except Exception:
    QWinTaskbarButton = None

from ui.ui_main import Ui_MainWindow

from gui.settings import Settings
from gui.about import About
from gui.device import Device
from gui.advanced_lag_settings import AdvancedLagSettingsDialog
from .traffic import Traffic

from networking.scanner import Scanner
from networking.killer import Killer
from networking.nicknames import nickname_profile_key, parse_nickname_profile_key

from tools.qtools import colored_item, MsgType, Buttons, clickable, TableRowNoCellFocusDelegate
from tools.utils_gui import (
    set_settings,
    get_settings,
    import_settings,
    is_admin,
    apply_app_global_dark_stylesheet,
    sync_translucent_chrome,
    register_window_surface_effects,
    table_row_hover_chrome,
    table_row_selection_chrome,
)
def format_countdown_ms(left_ms):
    """Human-readable countdown (matches Dupe / Lag Switch inline labels)."""
    left_ms = max(0, int(left_ms))
    if left_ms >= 60000:
        sec = left_ms // 1000
        m, s = divmod(sec, 60)
        return f'Time left: {m}:{s:02d}'
    if left_ms >= 1000:
        return f'Time left: {(left_ms + 999) // 1000} s'
    return f'Time left: {left_ms / 1000.0:.1f} s'


from tools.frameless_chrome import (
    FramelessResizableMixin,
    setup_frameless_main_window,
    CustomTitleBar,
)
from tools.clumsy_inline import (
    apply_clumsy_ics_router_context,
    clumsy_ics_lag_can_use_windivert,
    clumsy_ics_downstream_prefix,
    clumsy_ics_resolve_victim_ip,
    clumsy_ics_use_firewall_only,
    clumsy_windivert_unavailable_reason,
    clumsy_windivert_probe_detail,
    heal_ics_client_after_mitm,
    release_ics_victim_block,
    restore_ics_hotspot_connectivity,
    clumsy_mode_enabled,
    sync_clumsy_row,
    use_windivert_for_advanced_ics_shaping,
    victim_on_clumsy_ics_subnet,
)
from tools.keybinds import keyseq_from_setting
from tools.branding import (
    load_application_qicon,
    load_shell_window_icon,
    install_windows_native_window_icons,
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
from tools.pfctl import _is_valid_ip, block_ip, unblock_ip


def _dupe_net_run_unblock(ip: str) -> None:
    try:
        unblock_ip(ip)
    except Exception:
        pass


def _dupe_net_run_block(iface: str, ip: str, direction: str):
    try:
        block_ip(iface, ip, direction)
        return None
    except Exception as exc:
        return exc


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
        self.setMinimumWidth(400)

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
            _cb.setAttribute(Qt.WA_StyledBackground, True)
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
        self.normalSpin.setRange(1, 2147483647)
        self.normalSpin.setSingleStep(25)
        self.normalSpin.setValue(1500)
        self.normalSpin.setSuffix(' ms')
        timing_layout.addRow('Normal duration (allow time)', self.normalSpin)
        self.lagSpin.valueChanged.connect(self._on_timing_spin_changed)
        self.normalSpin.valueChanged.connect(self._on_timing_spin_changed)

        layout.addWidget(self.timing_group)

        self.lblLagCountdown = QLabel(body)
        self.lblLagCountdown.setAlignment(Qt.AlignCenter)
        self.lblLagCountdown.setWordWrap(True)
        cd_font = QFont(self.lblLagCountdown.font())
        cd_font.setPointSize(13)
        cd_font.setBold(True)
        self.lblLagCountdown.setFont(cd_font)
        self.lblLagCountdown.setVisible(False)
        layout.addWidget(self.lblLagCountdown)

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
        dev = main._get_selected_device()
        if not dev or not main._flow_matches_active_row(
            dev, main.lag_device_mac, getattr(main, 'lag_device_ip', None)
        ):
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
        if on and getattr(main, 'lag_active', False):
            self.set_lag_countdown(main.lag_remaining_ms(), main._lag_in_allow_phase)
        else:
            self.set_lag_countdown(None, False)

    def set_lag_countdown(self, left_ms, allow_phase: bool = False):
        """Show remaining time for the current lag or normal phase; None when idle."""
        _ = allow_phase  # kept for callers; both phases use the same countdown format
        if left_ms is None:
            self.lblLagCountdown.setVisible(False)
            self.lblLagCountdown.setText('')
            return
        self.lblLagCountdown.setVisible(True)
        self.lblLagCountdown.setText(format_countdown_ms(max(0, int(left_ms))))

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

        device = main._get_selected_device()
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
        self.setMinimumWidth(400)

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
            _cb.setAttribute(Qt.WA_StyledBackground, True)
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
        # Network may still be tearing down in the background; UI reads idle as soon as dupe_active is false.
        self._set_controls_enabled(not on)
        if on and getattr(main, 'dupe_active', False):
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
        self.lblDupeCountdown.setText(format_countdown_ms(left_ms))

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

        device = main._get_selected_device()
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
    mitm_teardown_finished = pyqtSignal(str, bool, str, bool, object)
    flow_net_main_done = pyqtSignal(object)

    def __init__(self, window_icon=None):
        super().__init__()
        self.version = '1.29'
        if window_icon is not None:
            self.shell_icon = window_icon
        else:
            self.shell_icon = load_shell_window_icon()
            if qicon_is_empty(self.shell_icon):
                self.shell_icon = self.processIcon(app_icon, crop_margins=True)
        # About toolbar: looser crop keeps the full gold outline; shell uses a tighter crop (larger on taskbar).
        self.icon = load_application_qicon(LOGO_UI_CONTENT_FRACTION)
        if qicon_is_empty(self.icon):
            self.icon = self.processIcon(app_icon, crop_margins=True)
        if qicon_is_empty(self.shell_icon):
            self.shell_icon = self.icon

        self.setWindowIcon(self.shell_icon)
        self.setupUi(self)
        self._admin_elevated = bool(sys.platform == 'win32' and is_admin())
        self.setWindowTitle(self._app_window_title())
        apply_app_global_dark_stylesheet()
        self.setStyleSheet('')
        # Rebalance top toolbar row so right-side empty space is used more evenly.
        self.gridLayout.removeWidget(self.btnSettings)
        self.gridLayout.removeWidget(self.btnAbout)
        # Flush Settings + About to columns 7–8; stretch 3–6 so the gap sits between scan cluster and right cluster.
        self.gridLayout.addWidget(self.btnSettings, 0, 7, 2, 1)
        self.gridLayout.addWidget(self.btnAbout, 0, 8, 2, 1)
        # Pre-72px look: 50px row height, 46px icons; wide buttons (not fixed squares) via equal column stretch + Expanding.
        for _tb in (self.btnScanEasy, self.btnScanHard, self.btnSettings, self.btnAbout):
            _tb.setMinimumHeight(50)
            _tb.setIconSize(QSize(46, 46))
            _tb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
        self.killed_devices = {}  # profile key (mac|subnet) -> explicit Kill toggle state
        # Per-MAC intent generation for kill toggle; delayed OFF reinforcement only runs
        # when generation still matches (prevents stale delayed actions from reapplying).
        self._kill_intent_seq = {}
        # Per-flow OFF intent generation (lag/dupe/unkill-all).
        self._flow_off_intent_seq = {}
        # Explicit Kill OFF in flight: ignore killer.killed fallback until _run_kill_command finishes.
        self._kill_teardown_mac = None
        self._kill_teardown_ip = None
        self.lag_active = False
        self.lag_block_ms = 9000
        self.lag_release_ms = 1500
        self._lag_reassert_gen = 0
        self._lag_phase_seq = 0
        self.lag_device_mac = None
        self.lag_device_ip = None
        self.lag_direction = 'both'  # 'both', 'in', or 'out'
        self._lag_phase_end_timer = QTimer(self)
        self._lag_phase_end_timer.setSingleShot(True)
        self._lag_phase_end_timer.setTimerType(Qt.PreciseTimer)
        self._lag_phase_end_timer.timeout.connect(self._lag_phase_end_timer_fired)
        self._lag_phase_deadline = 0.0
        self._lag_countdown_timer = QTimer(self)
        self._lag_countdown_timer.setInterval(50)
        # CoarseTimer keeps the label smooth; PreciseTimer on phase end handles block/allow timing.
        self._lag_countdown_timer.setTimerType(Qt.CoarseTimer)
        self._lag_countdown_timer.timeout.connect(self._tick_lag_countdown)
        self._lag_dlg_refresh_mono = 0.0
        self._lag_phase_advance_pending = False
        # False: block phase (Lag ms). True: allow phase (Normal ms).
        self._lag_in_allow_phase = False
        self._ics_wd_traffic_warn_session = None
        # Last started lag target; used on stop if the device row is missing from the scan list.
        self._lag_device_snapshot = None
        self._lag_restoring_after_stop = False
        self._lag_restoring_mac = None

        self.dupe_active = False
        self.dupe_device_mac = None
        self.dupe_device_ip = None
        self.dupe_direction = 'both'
        self.dupe_duration_ms = 5000
        self.percent_cut_active = False
        self.percent_cut_device_mac = None
        self.percent_cut_device_ip = None
        self.mitm_shaping_active = False
        self.mitm_shaping_mac = None
        self.mitm_shaping_device_ip = None
        self._mitm_shaping_backend = None  # None | 'forwarder' | 'windivert'
        self._ics_windivert_shaper = None
        self._ics_lag_gate = None
        self._ics_kill_profile_macs: set[str] = set()
        self._mitm_teardown_thread = None
        self._mitm_adv_sched_timer = QTimer(self)
        self._mitm_adv_sched_timer.setInterval(100)
        self._mitm_adv_sched_timer.setTimerType(Qt.PreciseTimer)
        self._mitm_adv_sched_timer.timeout.connect(self._mitm_adv_schedule_tick)
        self._mitm_adv_sched_t0 = 0.0
        self._mitm_adv_row_t0: dict[str, float] = {}
        self._mitm_adv_last_sched = None
        self.mitm_teardown_finished.connect(self._on_mitm_teardown_finished)
        self.flow_net_main_done.connect(self._on_flow_net_main_done)
        self._lag_dialog_target_mac = None
        self._dupe_dialog_target_mac = None
        self.dupe_timer = QTimer(self)
        self.dupe_timer.setSingleShot(True)
        self.dupe_timer.setTimerType(Qt.PreciseTimer)
        self.dupe_timer.timeout.connect(self._dupe_timer_fired)
        self._dupe_elapsed = QElapsedTimer()
        self._dupe_countdown_timer = QTimer(self)
        self._dupe_countdown_timer.setInterval(50)
        self._dupe_countdown_timer.setTimerType(Qt.CoarseTimer)
        self._dupe_countdown_timer.timeout.connect(self._tick_dupe_countdown)
        self._dupe_finish_from_countdown_pending = False
        self._dupe_arm_timer = QTimer(self)
        self._dupe_arm_timer.setSingleShot(True)
        self._dupe_deferred_clear_timer = QTimer(self)
        self._dupe_deferred_clear_timer.setSingleShot(True)
        self._dupe_pending_clear = None  # (mac, device_snapshot|None) for deferred unblock/unkill
        self._dupe_arm_device = None  # snapshot while deferred apply is pending
        self._dupe_restoring_after_stop = False  # true until async/sync dupe OFF clears firewall+ARP
        self._dupe_restoring_mac = None  # victim MAC during that window (pending clear may be cleared early)
        self._dupe_dlg_refresh_mono = 0.0
        self._dupe_net_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='dupe_net')
        self._dupe_end_mono = None  # wall deadline for countdown (set when block_ip finishes)
        self._dupe_clear_future = None
        self._dupe_async_unblock_ctx = None  # (device, prev_mac) until post-unblock slot runs
        self._dupe_block_future = None
        self._dupe_block_apply_pending = False
        self._dupe_block_ctx = None  # (device, direction) while block worker runs

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
        self.pgbar.setAttribute(Qt.WA_StyledBackground, True)

        # Update thread disabled for fork
        # self.update_thread = UpdateThread()
        # self.update_thread.thread_finished.connect(self.UpdateThread_Reciever)
        
        # Initialize other sub-windows
        self.settings_window = Settings(self, self.shell_icon)
        self.about_window = About(self, self.shell_icon)
        self.device_window = Device(self, self.shell_icon)
        self.traffic_window = Traffic(self, self.shell_icon)

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
        self.btnLagSwitch.pressed.connect(lambda: self._shortcut_global_lag())
        lag_font = QFont(self.btnLagSwitch.font())
        lag_font.setPointSize(13)
        lag_font.setBold(True)
        self.btnLagSwitch.setFont(lag_font)

        self.btnDupe = QPushButton('Dupe', self.centralwidget)
        self.btnDupe.setObjectName('btnDupe')
        self.btnDupe.setAttribute(Qt.WA_StyledBackground, True)
        self.btnDupe.setAutoDefault(False)
        self.btnDupe.setDefault(False)
        self.btnDupe.setMinimumHeight(72)
        self.btnDupe.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        dupe_font = QFont(self.btnDupe.font())
        dupe_font.setPointSize(13)
        dupe_font.setBold(True)
        self.btnDupe.setFont(dupe_font)
        self.btnDupe.setToolTip(
            'Dupe — one-shot lag for a set duration, then full stop. '
            'Duration/direction controls are always visible below. Shortcut: P.'
        )
        self.btnDupe.pressed.connect(lambda: self._shortcut_global_dupe())

        # Row was grid columns 3+2+3; equal stretch on outer columns keeps Lag and Dupe the same width
        # even when lblleft/lblright minimum widths skew shared column sizes.
        self._flowActionsRow = QWidget(self.centralwidget)
        self._flowActionsRow.setObjectName('flowActionsRow')
        _flow_actions_layout = QHBoxLayout(self._flowActionsRow)
        _flow_actions_layout.setContentsMargins(0, 0, 0, 0)
        _flow_actions_layout.setSpacing(self.gridLayout.spacing())
        _flow_actions_layout.addWidget(self.btnLagSwitch, 3)
        _flow_actions_layout.addWidget(self.btnKill, 2)
        _flow_actions_layout.addWidget(self.btnDupe, 3)
        self.gridLayout.addWidget(self._flowActionsRow, 5, 1, 1, 8)

        self.groupLagInline = QGroupBox('Lag Switch Controls', self.centralwidget)
        self.groupLagInline.setObjectName('groupLagInline')
        self.groupLagInline.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.groupLagInlineLayout = QVBoxLayout(self.groupLagInline)
        self.groupLagInlineLayout.setContentsMargins(8, 8, 8, 8)
        self.groupLagInlineLayout.setSpacing(4)
        self.lagTimingRow = QHBoxLayout()
        self.lagTimingRow.setSpacing(8)
        self.lagTimingRow.addWidget(QLabel('Lag', self.groupLagInline))
        self.lagSpinMain = QSpinBox(self.groupLagInline)
        self.lagSpinMain.setRange(1, 2147483647)
        self.lagSpinMain.setSingleStep(100)
        self.lagSpinMain.setValue(9000)
        self.lagSpinMain.setSuffix(' ms')
        self.lagTimingRow.addWidget(self.lagSpinMain)
        self.lagTimingRow.addSpacing(20)
        self.lagTimingRow.addWidget(QLabel('Normal', self.groupLagInline))
        self.normalSpinMain = QSpinBox(self.groupLagInline)
        self.normalSpinMain.setRange(1, 2147483647)
        self.normalSpinMain.setSingleStep(25)
        self.normalSpinMain.setValue(1500)
        self.normalSpinMain.setSuffix(' ms')
        self.lagTimingRow.addWidget(self.normalSpinMain)
        self.groupLagInlineLayout.addLayout(self.lagTimingRow)
        self.lagDirRow = QHBoxLayout()
        self.lagDirBoth = QCheckBox('Both', self.groupLagInline)
        self.lagDirBoth.setObjectName('zubcutFlowChkOn')
        self.lagDirBoth.setChecked(True)
        self.lagDirIncoming = QCheckBox('In', self.groupLagInline)
        self.lagDirIncoming.setObjectName('zubcutFlowChkDir')
        self.lagDirOutgoing = QCheckBox('Out', self.groupLagInline)
        self.lagDirOutgoing.setObjectName('zubcutFlowChkDir')
        for _cb in (self.lagDirBoth, self.lagDirIncoming, self.lagDirOutgoing):
            _cb.setAttribute(Qt.WA_StyledBackground, True)
        self.lagDirBoth.toggled.connect(
            lambda checked: checked and (self.lagDirIncoming.setChecked(False), self.lagDirOutgoing.setChecked(False))
        )
        self.lagDirRow.setSpacing(6)
        self.lagDirRow.addWidget(QLabel('Block', self.groupLagInline))
        self.lagDirRow.addWidget(self.lagDirBoth)
        _lag_dir_sep = QFrame(self.groupLagInline)
        _lag_dir_sep.setFrameShape(QFrame.NoFrame)
        _lag_dir_sep.setFixedSize(1, 18)
        _lag_dir_sep.setStyleSheet('background-color: #316E69; border-radius: 1px; margin-left: 10px; margin-right: 8px;')
        self.lagDirRow.addWidget(_lag_dir_sep)
        self.lagDirRow.addWidget(self.lagDirIncoming)
        self.lagDirRow.addWidget(self.lagDirOutgoing)
        self.groupLagInlineLayout.addLayout(self.lagDirRow)
        self.lblLagCountdownMain = QLabel('', self.groupLagInline)
        self.lblLagCountdownMain.setObjectName('lblLagCountdownMain')
        self.lblLagCountdownMain.setVisible(False)
        self.groupLagInlineLayout.addWidget(self.lblLagCountdownMain)
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
        self.dupeDirBoth.setObjectName('zubcutFlowChkOn')
        self.dupeDirBoth.setChecked(True)
        self.dupeDirIncoming = QCheckBox('In', self.groupDupeInline)
        self.dupeDirIncoming.setObjectName('zubcutFlowChkDir')
        self.dupeDirOutgoing = QCheckBox('Out', self.groupDupeInline)
        self.dupeDirOutgoing.setObjectName('zubcutFlowChkDir')
        for _cb in (self.dupeDirBoth, self.dupeDirIncoming, self.dupeDirOutgoing):
            _cb.setAttribute(Qt.WA_StyledBackground, True)
        self.dupeDirBoth.toggled.connect(
            lambda checked: checked and (self.dupeDirIncoming.setChecked(False), self.dupeDirOutgoing.setChecked(False))
        )
        self.dupeDirRow.setSpacing(6)
        self.dupeDirRow.addWidget(QLabel('Block', self.groupDupeInline))
        self.dupeDirRow.addWidget(self.dupeDirBoth)
        _dupe_dir_sep = QFrame(self.groupDupeInline)
        _dupe_dir_sep.setFrameShape(QFrame.NoFrame)
        _dupe_dir_sep.setFixedSize(1, 18)
        _dupe_dir_sep.setStyleSheet('background-color: #316E69; border-radius: 1px; margin-left: 10px; margin-right: 8px;')
        self.dupeDirRow.addWidget(_dupe_dir_sep)
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

        # Same minimum width for all inline timing / percent spinboxes (short "%" values shrink the Cut % box otherwise).
        _inline_spin_min_w = 140
        for _sb in (
            self.lagSpinMain,
            self.normalSpinMain,
            self.dupeSpinMain,
            self.spinPercentCutMain,
        ):
            _sb.setMinimumWidth(_inline_spin_min_w)

        self.btnPercentCut = QPushButton('Percent Cut: OFF', self.centralwidget)
        self.btnPercentCut.setObjectName('btnPercentCut')
        self.btnPercentCut.setAttribute(Qt.WA_StyledBackground, True)
        self.btnPercentCut.setAutoDefault(False)
        self.btnPercentCut.setDefault(False)
        self.btnPercentCut.setMinimumHeight(72)
        self.btnPercentCut.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btnPercentCut.setToolTip(
            'Percent Cut — drops that much of the victim traffic (1% cut ≈ 99% still passes). '
            'On PC hotspot uses WinDivert byte budgeting, not full pause. Shortcut: K.'
        )
        self.gridLayout.addWidget(self.btnPercentCut, 7, 6, 1, 3)
        self.btnPercentCut.pressed.connect(lambda: self.togglePercentCut('mouse_pressed'))
        for _flow_btn in (self.btnKill, self.btnLagSwitch, self.btnDupe, self.btnPercentCut):
            _flow_btn.setContextMenuPolicy(Qt.CustomContextMenu)
            _flow_btn.customContextMenuRequested.connect(self._on_main_flow_toggle_context_menu)

        self.sliderPercentCutMain.valueChanged.connect(self.spinPercentCutMain.setValue)
        self.spinPercentCutMain.valueChanged.connect(self.sliderPercentCutMain.setValue)
        self.spinPercentCutMain.valueChanged.connect(self._on_percent_cut_value_changed)
        self.sliderPercentCutMain.setValue(self._percent_cut_value())

        self.lag_switch_dialog = None
        self.dupe_switch_dialog = None
        self.advanced_lag_settings_dialog = None
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
        self.tray_icon.setIcon(self.shell_icon)
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

        # Windows: caption uses shell_icon so title strip + DWM hover match the .exe/.ico (UI crop looks thin).
        _caption_icon = self.shell_icon if sys.platform == 'win32' else self.icon
        setup_frameless_main_window(self, self._app_window_title(), _caption_icon, maximizable=True)
        _chrome_windows = [
            self,
            self.settings_window,
            self.about_window,
            self.device_window,
            self.traffic_window,
        ]
        if self.advanced_lag_settings_dialog is not None:
            _chrome_windows.append(self.advanced_lag_settings_dialog)
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
        self.settings_window.loadInterfaces(use_cache=True)
        self.settings_window.currentSettings()
        self.settings_window.show()
        self.settings_window.setWindowState(Qt.WindowNoState)
        QTimer.singleShot(0, self.settings_window._load_interfaces_background)

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

    def _on_main_flow_toggle_context_menu(self, pos):
        w = self.sender()
        if w is None:
            return
        menu = QMenu(self)
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
        self._apply_scan_table_column_layout()

    def _sync_scan_table_column_settings(self):
        try:
            mac = bool(get_settings('show_scan_mac_column'))
            ven = bool(get_settings('show_scan_vendor_column'))
        except Exception:
            mac, ven = False, False
        self.tableScan.setColumnHidden(SCAN_TABLE_COLUMN_MAC, not mac)
        self.tableScan.setColumnHidden(SCAN_TABLE_COLUMN_VENDOR, not ven)
        self._apply_scan_table_column_layout()

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
            self.log(
                'No response — no MAC in ARP for that IP yet (wrong interface, offline host, '
                'or need Admin/Npcap for direct probe). Try a normal scan or pick the LAN adapter in Settings.',
                'red',
            )

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

    def _teardown_all_attacks(self, *, log: bool = False) -> dict:
        """Stop lag/kill/dupe/MITM and remove all ZubCut firewall blocks (exit + startup)."""
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

    def _ensure_clean_network_on_startup(self) -> None:
        """Remove leftover Kill/Dupe/Lag blocks from a prior session before the user acts."""
        from tools.clumsy_ics import purge_clumsy_stale_attack_blocks
        from tools.pfctl import list_blocked_ips

        purge_clumsy_stale_attack_blocks()
        pre = list_blocked_ips()
        summary = self._teardown_all_attacks(log=False)
        try:
            from tools.clumsy_inline import heal_all_hotspot_arp_clients

            healed = heal_all_hotspot_arp_clients(self.scanner, self.killer)
            if healed:
                self.log(
                    f'Restored hotspot gateway ARP for {healed} console(s).',
                    UI_LOG_RESTORE_FG,
                )
        except Exception:
            pass
        removed = int(summary.get('firewall_rules_removed') or 0)
        ips = summary.get('unblocked_ips') or []
        if removed or ips or pre:
            msg = 'Removed leftover attack state from a previous session.'
            if removed:
                msg += f' ({removed} firewall rule(s))'
            if ips:
                msg += f' ({len(ips)} IP unblocked)'
            self.log(msg, UI_LOG_RESTORE_FG)

    def quit_all(self):
        """
        Unkill any killed device on exit from tray icon
        """
        self._teardown_all_attacks(log=True)
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
        if sys.platform == 'win32':
            # Qt may (re)apply small window icons after first show; push Win32 icons several times.
            def _push_hwnd_icons():
                install_windows_native_window_icons(self)

            _push_hwnd_icons()
            QTimer.singleShot(50, _push_hwnd_icons)
            QTimer.singleShot(300, _push_hwnd_icons)
            QTimer.singleShot(1200, _push_hwnd_icons)

        if QWinTaskbarButton is None:
            return
        if getattr(self, '_taskbar_progress_linked', False):
            return
        self._taskbar_progress_linked = True
        self.taskbar_button = QWinTaskbarButton()
        self.taskbar_progress = self.taskbar_button.progress()
        self.taskbar_button.setWindow(self.windowHandle())
        self.pgbar.valueChanged.connect(self.taskbar_progress.setValue)

    def _apply_scan_table_column_layout(self):
        """
        Split table width evenly across visible columns. Hidden MAC/Vendor columns
        do not consume space (Stretch only on visible sections).
        """
        hh = self.tableScan.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(56)
        for c in range(self.tableScan.columnCount()):
            if self.tableScan.isColumnHidden(c):
                hh.setSectionResizeMode(c, QHeaderView.Fixed)
            else:
                hh.setSectionResizeMode(c, QHeaderView.Stretch)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_scan_table_column_layout()
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
        try:
            self._dupe_net_executor.shutdown(wait=False, cancel_futures=False)
        except TypeError:
            self._dupe_net_executor.shutdown(wait=False)
        except Exception:
            pass
        # If event recieved from tray icon
        if self.from_tray:
            hide_all_system_tray_icons()
            event.accept()
            return

        # Close button path: tear down all attacks then exit.
        self._teardown_all_attacks(log=False)
        self.settings_window.close()
        self.about_window.close()

        self.hide()
        hide_all_system_tray_icons()

        event.accept()

    def _app_window_title(self) -> str:
        if getattr(self, '_admin_elevated', False):
            return f'{APP_DISPLAY_NAME} — Administrator'
        return APP_DISPLAY_NAME

    def current_index(self):
        return self.scanner.devices[self.tableScan.currentRow()]
    
    def cellClicked(self, row, column):
        """
        Copy selected cell data to clipboard
        """
        # Get current row
        device = self.current_index()

        keys_order = ['ip', 'mac', 'vendor', 'type', 'name']
        if column < 0 or column >= len(keys_order):
            return
        cell = str(device.get(keys_order[column], ''))

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
        # Keep inline panels usable while lag/dupe runs on a victim row even if user selects admin/Me
        # (otherwise the whole group disables and the countdown looks frozen or "off").
        self.groupLagInline.setEnabled(not_enabled or bool(self.lag_active and self.lag_device_mac))
        self.groupDupeInline.setEnabled(not_enabled or bool(self.dupe_active and self.dupe_device_mac))
        
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

    def _device_profile_key(self, device) -> str:
        if not device:
            return ''
        return nickname_profile_key(device.get('mac', ''), device.get('ip', ''))

    def _killed_profile_key(self, device) -> str:
        pk = self._device_profile_key(device)
        if pk:
            return pk
        return str(device.get('mac') or '').strip()

    def _flow_matches_row(self, device, flow_mac, flow_ip=None) -> bool:
        if not device or not flow_mac or device.get('mac') != flow_mac:
            return False
        want = (flow_ip or '').strip()
        if not want:
            # Same MAC on home LAN + hotspot: never highlight every nickname row.
            peers = [
                d
                for d in self.scanner.devices
                if d.get('mac') == flow_mac and not d.get('admin')
            ]
            return len(peers) <= 1
        return (str(device.get('ip') or '').strip() == want)

    def _flow_matches_active_row(self, device, flow_mac, flow_ip=None) -> bool:
        """Match lag/dupe/kill flows to one table row (MAC + IP)."""
        if flow_ip:
            return self._flow_matches_row(device, flow_mac, flow_ip)
        snap_ip = ''
        if getattr(self, 'lag_active', False) and flow_mac == getattr(self, 'lag_device_mac', None):
            snap = getattr(self, '_lag_device_snapshot', None)
            if isinstance(snap, dict):
                snap_ip = str(snap.get('ip') or '').strip()
        if getattr(self, 'dupe_active', False) and flow_mac == getattr(self, 'dupe_device_mac', None):
            snap = getattr(self, '_dupe_arm_device', None)
            if isinstance(snap, dict):
                snap_ip = str(snap.get('ip') or '').strip()
        if snap_ip:
            return self._flow_matches_row(device, flow_mac, snap_ip)
        return self._flow_matches_row(device, flow_mac, flow_ip)

    def _killed_profile_on(self, device) -> bool:
        pk = self._killed_profile_key(device)
        return bool(pk and self.killed_devices.get(pk, False))

    def _set_killed_profile(self, device, on: bool) -> None:
        pk = self._killed_profile_key(device)
        if pk:
            self.killed_devices[pk] = bool(on)

    def _device_for_kill_profile(self, profile_key: str):
        for d in self.scanner.devices:
            if self._killed_profile_key(d) == profile_key:
                return d
        mac, _prefix = parse_nickname_profile_key(profile_key)
        if mac:
            return self._victim_record_for_mac(mac)
        return None

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
        if not self._killed_profile_on(device):
            return False
        return mac in self.killer.killed

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
        texts = [
            str(device.get('ip', '')),
            str(device.get('mac', '')),
            str(device.get('vendor', '')),
            str(device.get('type', '')),
            str(device.get('name', '')),
        ]
        for column, text in enumerate(texts):
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
        try:
            sync_clumsy_row(self.scanner)
        except Exception:
            pass
        try:
            self.scanner.inject_nicknamed_favorites()
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

        self._update_scan_count_status()

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
        for mac, victim in self.killer.killed.items():
            pk = nickname_profile_key(mac, victim.get('ip', ''))
            if pk:
                self.killed_devices[pk] = True
        self._sync_killed_devices()

        # clear old database
        self.killer.release()

        n_clients = len([d for d in self.scanner.devices if not d.get('admin')])
        self.log(
            f'Found {n_clients} devices.',
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
        if not _is_valid_ip(device.get('ip') or ''):
            self.log('Target has no IP yet — enable Internet sharing and rescan.', 'red')
            return

        if device['mac'] in self.killer.killed:
            self.log('Device is already killed', 'red')
            return
        
        if clumsy_ics_use_firewall_only(device, self.scanner):
            if not self._apply_victim_block(device, 'both'):
                return
            self._set_killed_profile(device, True)
        else:
            self._ensure_network_context_for_victim(device)
            self.killer.kill(device)
            try:
                iface = self.scanner.iface.name if self.scanner.iface else 'en0'
                block_ip(iface, device['ip'], 'both')
            except Exception:
                pass
            self._set_killed_profile(device, True)
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
        self._flush_pending_dupe_clear_sync()
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
        if clumsy_ics_use_firewall_only(victim, self.scanner):
            self._clear_victim_block(victim)
            self._stop_ics_lag_gate()
        else:
            self._ensure_network_context_for_victim(victim)
            try:
                unblock_ip(victim.get('ip') or '')
            except Exception:
                pass
            self.killer.unkill(victim)
        self._set_killed_profile(device, False)
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
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)
        self.stop_mitm_shaping(log=False)
        self._await_mitm_teardown_thread()
        if not self.connected():
            return
        
        for d in self.scanner.devices:
            if d.get('admin'):
                continue
            if clumsy_ics_use_firewall_only(d, self.scanner):
                self._apply_victim_block(d, 'both')
                self._set_killed_profile(d, True)
            else:
                self.killer.kill(d)
                try:
                    iface = self.scanner.iface.name if self.scanner.iface else 'en0'
                    block_ip(iface, d['ip'], 'both')
                except Exception:
                    pass
                self._set_killed_profile(d, True)
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
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)
        self.stop_mitm_shaping(log=False)
        self._await_mitm_teardown_thread()
        if not self.connected():
            return
        
        victims_before = [dict(v) for v in self.killer.killed.values()]
        for d in self.scanner.devices:
            if clumsy_ics_use_firewall_only(d, self.scanner):
                try:
                    self._clear_victim_block(d)
                except Exception:
                    pass
        self._stop_ics_lag_gate()
        for v in victims_before:
            if clumsy_ics_use_firewall_only(v, self.scanner):
                continue
            try:
                unblock_ip(v.get('ip') or '')
            except Exception:
                pass
        self.killer.unkill_all(self.scanner)
        for victim in victims_before:
            mac = victim.get('mac')
            if not mac:
                continue
            if clumsy_ics_use_firewall_only(victim, self.scanner):
                continue
            # OFF-only reinforcement for bulk unkill (same cadence as per-device kill OFF).
            self.killer.reinforce_restore(victim)
            off_seq = self._bump_flow_off_intent('all', mac)
            self._schedule_flow_off_reinforce('all', mac, off_seq, 25, victim)
            self._schedule_flow_off_reinforce('all', mac, off_seq, 100, victim)
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
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)
        self.stop_mitm_shaping(log=False)
        self._await_mitm_teardown_thread()
        if not self.connected(show_msg_box=True):
            return

        self.centralwidget.setEnabled(False)
        
        # Save copy of killed devices
        self.killer.store()
        
        _pre_scan_ips = [v.get('ip') for v in self.killer.killed.values() if v.get('ip')]
        self.killer.unkill_all(self.scanner)
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
        self._start_clumsy_inline_refresh_timer()

    def UpdateThread_Reciever(self):
        """
        Legacy hook from upstream; unused.
        """
        pass

    def _start_clumsy_inline_refresh_timer(self):
        """While Clumsy mode is on, periodically re-resolve ICS console IP (ARP + rate-limited ping)."""
        import sys

        if not sys.platform.startswith('win'):
            return
        if getattr(self, '_clumsy_inline_refresh_timer', None) is None:
            self._clumsy_inline_refresh_timer = QTimer(self)
            self._clumsy_inline_refresh_timer.setInterval(7000)
            self._clumsy_inline_refresh_timer.timeout.connect(self._refresh_clumsy_inline_row_if_needed)
        self._clumsy_inline_refresh_timer.start()

    def _refresh_clumsy_inline_row_if_needed(self):
        """While Clumsy mode is on, periodically re-sync ICS dedupe from ARP only.

        Do not pass allow_subnet_ping here: that path runs many sequential pings on
        whatever thread calls it; on the GUI thread it froze the app for seconds
        (especially when the console is no longer on the ICS subnet, e.g. plugged
        straight into the router while Clumsy stays enabled in settings).
        ICS subnet ping discovery runs from the scan thread in devices_appender.
        """
        if getattr(self, 'lag_active', False) or getattr(self, 'dupe_active', False):
            return
        try:
            from tools.clumsy_inline import (
                clumsy_mode_enabled,
                clumsy_runtime_ready,
                detect_inline_ip,
                sync_clumsy_row,
            )

            if not clumsy_mode_enabled() or not clumsy_runtime_ready():
                t = getattr(self, '_clumsy_inline_refresh_timer', None)
                if t is not None and t.isActive():
                    t.stop()
                return

            ip_before = detect_inline_ip(self.scanner, allow_subnet_ping=False)
            n_before = len(self.scanner.devices)
            sync_clumsy_row(self.scanner, allow_subnet_ping=False)
            n_after = len(self.scanner.devices)
            ip_after = detect_inline_ip(self.scanner, allow_subnet_ping=False)
            if ip_before != ip_after or n_before != n_after:
                self.showDevices()
        except Exception:
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
        device = self._get_selected_device()
        if device is None:
            self.log('No device selected', 'red')
            return
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
        device = self._get_selected_device()
        if device is None:
            self.log('No device selected', 'red')
            return
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
            f'QGroupBox#groupLagInline QCheckBox#zubcutFlowChkOn::indicator, QGroupBox#groupDupeInline QCheckBox#zubcutFlowChkOn::indicator {{'
            f' image: none; width: 16px; height: 16px; border-radius: 3px; border: 1px solid {sel_bg};'
            f' background-color: transparent; margin: 0px; }}'
            f'QGroupBox#groupLagInline QCheckBox#zubcutFlowChkOn::indicator:checked, QGroupBox#groupDupeInline QCheckBox#zubcutFlowChkOn::indicator:checked {{'
            f' background-color: {sel_bg}; border: 1px solid {sel_bg}; }}'
            f'QGroupBox#groupLagInline QCheckBox#zubcutFlowChkOn::indicator:hover, QGroupBox#groupDupeInline QCheckBox#zubcutFlowChkOn::indicator:hover,'
            f'QGroupBox#groupLagInline QCheckBox#zubcutFlowChkOn::indicator:unchecked:hover, QGroupBox#groupDupeInline QCheckBox#zubcutFlowChkOn::indicator:unchecked:hover {{'
            f' border: 1px solid {sel_bg}; }}'
            f'QGroupBox#groupLagInline QCheckBox#zubcutFlowChkDir::indicator, QGroupBox#groupDupeInline QCheckBox#zubcutFlowChkDir::indicator {{'
            f' image: none; width: 13px; height: 13px; border-radius: 2px; border: 1px solid #5D706E;'
            f' background-color: transparent; margin: 0px; }}'
            f'QGroupBox#groupLagInline QCheckBox#zubcutFlowChkDir::indicator:unchecked, QGroupBox#groupDupeInline QCheckBox#zubcutFlowChkDir::indicator:unchecked {{'
            f' border: 1px solid #5D706E; }}'
            f'QGroupBox#groupLagInline QCheckBox#zubcutFlowChkDir::indicator:checked, QGroupBox#groupDupeInline QCheckBox#zubcutFlowChkDir::indicator:checked {{'
            f' background-color: {sel_bg}; border: 1px solid #5D706E; }}'
            f'QGroupBox#groupLagInline QCheckBox#zubcutFlowChkDir::indicator:hover, QGroupBox#groupDupeInline QCheckBox#zubcutFlowChkDir::indicator:hover,'
            f'QGroupBox#groupLagInline QCheckBox#zubcutFlowChkDir::indicator:unchecked:hover, QGroupBox#groupDupeInline QCheckBox#zubcutFlowChkDir::indicator:unchecked:hover {{'
            f' border: 1px solid {sel_bg}; }}'
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
            f'QLabel#lblDupeCountdownMain, QLabel#lblLagCountdownMain {{ color: {sel_bg}; font-weight: bold; }}'
        )
        self.groupLagInline.setStyleSheet(panel_style)
        self.groupDupeInline.setStyleSheet(panel_style)
        percent_style = (
            f'QLabel#lblPercentCut {{ color: {admin_bg}; background-color: transparent; }}'
            f'QSpinBox#spinPercentCutMain {{'
            f' min-height: 24px; border: 1px solid {admin_bg}; border-radius: 4px;'
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
        if not _is_valid_ip(device.get('ip') or ''):
            self.log('Target has no IP yet — cannot start lag.', 'red')
            return
        if self._toggle_start_blocked('lag'):
            return
        self.stopDupe(refresh_dialog=True, log=False)
        if self._dupe_pending_clear or getattr(self, '_dupe_clear_future', None):
            self._flush_pending_dupe_clear_sync(max_wait_ms=400)
        self._drop_dupe_restoring_banner()
        self.stop_mitm_shaping(log=False)
        if self.percent_cut_active:
            self.stopPercentCut(log=False)
        if self.lag_active:
            self.stopLagSwitch(refresh_dialog=False)
        self.lag_device_mac = device['mac']
        resolved_ip = self._ics_hotspot_victim_ip(device, lag=True) or clumsy_ics_resolve_victim_ip(
            device, self.scanner
        )
        self.lag_device_ip = resolved_ip or device.get('ip')
        snap = dict(device)
        if resolved_ip:
            snap['ip'] = resolved_ip
        self._lag_device_snapshot = snap
        self.lag_active = True
        self._refresh_lag_timing_from_dialog()
        self.btnLagSwitch.setText('■ LAGGING')
        self.btnLagSwitch.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        dir_text = {'both': 'all', 'in': 'incoming', 'out': 'outgoing'}[self.lag_direction]
        self.log(
            f'Lag switch ON: {self.lag_block_ms}ms lag ({dir_text}) / {self.lag_release_ms}ms normal',
            UI_LOG_VICTIM_BLOCK_FG,
        )
        dev = dict(device)
        mac = device['mac']

        def _arm_lag_start():
            if not self.lag_active or self.lag_device_mac != mac:
                return
            cur = self._lag_resolved_victim() or dev
            self._lag_phase_begin_block(cur)
            self._schedule_lag_start_reassert(mac)
            self._refresh_flow_toggle_ui()
            self._repaint_all_table_rows_for_hover()

        self._refresh_flow_toggle_ui()
        self._repaint_all_table_rows_for_hover()
        _arm_lag_start()

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
            try:
                self._lag_apply_block(dev)
            except Exception:
                pass

        QTimer.singleShot(0, _reassert)
        QTimer.singleShot(40, _reassert)
        QTimer.singleShot(110, _reassert)

    def _update_scan_count_status(self):
        """Update device/kill counts in lblright + tray without rebuilding the scan table."""
        try:
            n = max(0, len(self.scanner.devices) - 2)
            self.lblright.setText(f'{n} devices ({len(self.killer.killed)} killed)')
            if getattr(self, 'tray_icon', None) and getattr(self.scanner, 'iface', None):
                self.tray_icon.setToolTip(
                    f'Devices Found: {n}\n'
                    f'Devices Killed: {len(self.killer.killed)}\n'
                    f'Interface: {self.scanner.iface.name}'
                )
        except Exception:
            pass

    def _refresh_table_row_for_mac(self, mac, ip=None):
        """Update table row colors for one MAC (all subnet rows unless ip is set)."""
        if not mac:
            return
        want_ip = (ip or '').strip()
        for row, d in enumerate(self.scanner.devices):
            if d['mac'] != mac:
                continue
            if want_ip and (d.get('ip') or '').strip() != want_ip:
                continue
            self.fillTableRow(row, d)
            self._repaint_table_row_for_hover(row)
            if want_ip:
                return

    def _ensure_network_context_for_victim(self, device) -> bool:
        """
        Bind scanner + killer to the NIC that routes to the victim (e.g. hotspot vs Ethernet).
        Runtime only — does not write ``iface`` to settings (so Clumsy/victim auto-pick
        does not replace your chosen adapter in zubcut.json).

        Applies the network stack prep that Clumsy enable/repair + restart used to do
        implicitly (ARP flush, topology refresh, Windows IP forwarding).
        """
        if not device or not device.get('ip'):
            return False
        changed = False
        try:
            changed = bool(self.scanner.sync_iface_for_victim_ip(device['ip']))
        except Exception:
            pass
        if not clumsy_mode_enabled():
            try:
                self.scanner.flush_arp()
            except Exception:
                pass
        try:
            self.scanner.refresh_local_topology()
        except Exception:
            pass
        if clumsy_mode_enabled():
            try:
                apply_clumsy_ics_router_context(self.scanner, self.killer, device['ip'])
            except Exception:
                pass
        self.killer.iface = self.scanner.iface
        self.killer.router = self.scanner.router
        self.killer._close_socket()
        try:
            from networking.killer import enable_ip_forwarding

            enable_ip_forwarding()
        except Exception:
            pass
        try:
            from scapy.all import conf as scapy_conf

            guid = self.scanner.iface.guid if self.scanner.iface else None
            if guid:
                scapy_conf.iface = guid
        except Exception:
            pass
        if changed:
            label = (getattr(self.scanner.iface, 'name', None) or '').strip() or getattr(
                self.scanner.iface, 'guid', ''
            )
            self.log(
                f'Using network adapter for {device["ip"]}: {label}',
                UI_LOG_RESTORE_FG,
            )
        return True

    def _clear_stale_ics_mitm(self, device) -> None:
        """Drop ARP MITM left on a hotspot client from an older build or non-ICS path."""
        if device['mac'] not in self.killer.killed:
            return
        try:
            victim = self._victim_record_for_mac(device['mac']) or device
            self.killer.unkill(victim)
        except Exception:
            pass

    def _schedule_dupe_off_reinforce(self, prev_mac, device) -> None:
        """ARP reinforce only; WinDivert-only ICS dupe skips delayed callbacks."""
        if not device or not prev_mac:
            return
        if clumsy_ics_use_firewall_only(device, self.scanner) and prev_mac not in self.killer.killed:
            return
        dupe_off_seq = self._bump_flow_off_intent('dupe', prev_mac)
        self._schedule_flow_off_reinforce('dupe', prev_mac, dupe_off_seq, 25, device)
        self._schedule_flow_off_reinforce('dupe', prev_mac, dupe_off_seq, 100, device)

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
        resolved = self._flow_stable_victim_ip(
            device,
            lag=getattr(self, 'lag_active', False),
            dupe=getattr(self, 'dupe_active', False),
        )
        if not resolved:
            resolved = clumsy_ics_resolve_victim_ip(device, self.scanner)
        table_ip = str(device.get('ip') or '').strip()
        return gate.victim_ip in (resolved, table_ip)

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
        """Stop ARP MITM / forwarder paths so WinDivert partial shaping is not stacked on Kill."""
        if not isinstance(device, dict):
            return
        mac = str(device.get('mac') or '').strip()
        if not mac:
            return
        victim = self._victim_record_for_mac(mac) or device
        try:
            self.killer.disable_percent_cut(mac)
        except Exception:
            pass
        if mac in self.killer.killed:
            try:
                if clumsy_ics_use_firewall_only(victim, self.scanner):
                    release_ics_victim_block(self.scanner, self.killer, victim)
                else:
                    self.killer.unkill(victim)
            except Exception:
                pass
        try:
            ip = (
                clumsy_ics_resolve_victim_ip(victim, self.scanner)
                or str(victim.get('ip') or '').strip()
            )
            if ip:
                unblock_ip(ip)
        except Exception:
            pass

    def _ics_device_with_resolved_ip(self, device) -> dict:
        dev = dict(device) if isinstance(device, dict) else {}
        ip = clumsy_ics_resolve_victim_ip(dev, self.scanner) or str(dev.get('ip') or '').strip()
        if ip:
            dev['ip'] = ip
        return dev

    def _ics_hotspot_victim_ip(
        self,
        device,
        *,
        lag: bool = False,
        dupe: bool = False,
        pctcut: bool = False,
        mitmshape: bool = False,
    ) -> str:
        """Resolved 137.x hotspot IP for WinDivert, or '' if the console is not on ICS."""
        dev = self._ics_device_with_resolved_ip(device)
        ip = self._flow_stable_victim_ip(
            dev, lag=lag, dupe=dupe, pctcut=pctcut, mitmshape=mitmshape
        )
        if not ip:
            ip = str(dev.get('ip') or '').strip()
        if not victim_on_clumsy_ics_subnet(ip):
            resolved = clumsy_ics_resolve_victim_ip(dev, self.scanner)
            if resolved and victim_on_clumsy_ics_subnet(resolved):
                ip = resolved.strip()
        if victim_on_clumsy_ics_subnet(ip):
            return ip
        return ''

    def _ics_apply_percent_cut_windivert(self, device, cut_pct: int) -> bool:
        """Hotspot partial cut via WinDivert (Bernoulli per packet, not pause / Kill)."""
        device = self._ics_device_with_resolved_ip(device)
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
        """Hotspot Advanced Lag via WinDivert shaping (not pause / Kill)."""
        device = self._ics_device_with_resolved_ip(device)
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
            victim = dict(device)
            victim['ip'] = resolved_ip
            self._schedule_ics_hotspot_heal(victim)

    def _ics_hotspot_pause_release(self, device, *, heal: bool = False) -> None:
        """
        Hotspot lag allow / traffic resume: Kill-OFF-equivalent (stop gate + unblock IP).
        Leaves killer.killed / killed_devices unchanged when lag was not mirroring Kill.
        """
        if not isinstance(device, dict) or not clumsy_ics_use_firewall_only(device, self.scanner):
            return
        self._ics_hotspot_windivert_teardown(device, heal=heal)
        ip = (
            self._flow_stable_victim_ip(device, lag=True)
            or clumsy_ics_resolve_victim_ip(device, self.scanner)
            or str(device.get('ip') or '').strip()
        )
        if ip:
            try:
                unblock_ip(ip)
            except Exception:
                pass

    def _release_ics_windivert_block(self, device, *, heal: bool = True) -> None:
        """Full WinDivert OFF: unpause, stop gate, clear killer bookkeeping, heal PS5 gateway ARP."""
        if not isinstance(device, dict):
            return
        mac = str(device.get('mac') or '').strip()
        self._ics_hotspot_windivert_teardown(device, heal=heal)
        if mac:
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
        """
        if not isinstance(device, dict) or not clumsy_ics_use_firewall_only(device, self.scanner):
            return
        self._release_ics_windivert_block(device, heal=heal)
        mac = str(device.get('mac') or '').strip()
        victim = self._victim_record_for_mac(mac) or device
        if mac and mac in self.killer.killed:
            try:
                release_ics_victim_block(self.scanner, self.killer, victim)
            except Exception:
                pass
        ip = clumsy_ics_resolve_victim_ip(device, self.scanner) or str(device.get('ip') or '')
        if ip:
            try:
                unblock_ip(ip)
            except Exception:
                pass

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
        Once per new gate: hint if WinDivert never sees traffic for the filter IP.

        Not used while Kill/Dupe/Lag (or other flows) are pausing the victim — zero packets
        then usually means the pause worked, not that the PS5 is offline.
        """
        ip = str(victim_ip or '').strip()
        if self._ics_victim_impairment_active(ip):
            return
        gate = getattr(self, '_ics_lag_gate', None)
        if gate is None or gate.victim_ip != ip:
            return
        session = id(gate)
        if getattr(self, '_ics_wd_traffic_warn_session', None) == session:
            return
        self._ics_wd_traffic_warn_session = session

        def _check() -> None:
            gate = getattr(self, '_ics_lag_gate', None)
            if gate is None or gate.victim_ip != ip or not gate.is_running():
                return
            if self._ics_victim_impairment_active(ip):
                return
            if gate.packets_matched > 0 or gate.packets_seen > 0:
                return
            if gate.packets_held > 0:
                return
            layers = gate.active_layers or ()
            self.log(
                f'WinDivert is open but no packets yet for {ip} '
                f'(layers {layers}, seen {gate.packets_seen}). '
                'Generate traffic on the PS5 (game, store, or connection test), then try again.',
                'red',
            )

        QTimer.singleShot(5000, _check)

    def _flow_stable_victim_ip(
        self,
        device,
        *,
        lag: bool = False,
        dupe: bool = False,
        pctcut: bool = False,
        mitmshape: bool = False,
    ) -> str:
        """Pinned ICS IP while a flow runs — avoids gate on wrong address after rescan."""
        if lag and getattr(self, 'lag_active', False):
            ip = (getattr(self, 'lag_device_ip', None) or '').strip()
            if ip:
                return ip
        if dupe and getattr(self, 'dupe_active', False):
            ip = (getattr(self, 'dupe_device_ip', None) or '').strip()
            if ip:
                return ip
        if pctcut and getattr(self, 'percent_cut_active', False):
            ip = (getattr(self, 'percent_cut_device_ip', None) or '').strip()
            if ip:
                return ip
        if mitmshape and getattr(self, 'mitm_shaping_active', False):
            ip = (getattr(self, 'mitm_shaping_device_ip', None) or '').strip()
            if ip:
                return ip
        if isinstance(device, dict):
            return clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
                device.get('ip') or ''
            ).strip()
        return ''

    def _ensure_ics_lag_gate(self, device, direction: str) -> bool:
        if not clumsy_ics_lag_can_use_windivert(device, self.scanner):
            return False
        ip = self._ics_hotspot_victim_ip(
            device,
            lag=getattr(self, 'lag_active', False),
            dupe=getattr(self, 'dupe_active', False),
            pctcut=getattr(self, 'percent_cut_active', False),
            mitmshape=getattr(self, 'mitm_shaping_active', False),
        )
        if not ip and isinstance(device, dict):
            ip = str(device.get('ip') or '').strip()
        if not victim_on_clumsy_ics_subnet(ip):
            resolved = clumsy_ics_resolve_victim_ip(device, self.scanner)
            if resolved and victim_on_clumsy_ics_subnet(resolved):
                ip = resolved.strip()
        if not ip or not victim_on_clumsy_ics_subnet(ip):
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
                if getattr(self, 'percent_cut_active', False):
                    pct = self._clamp_percent(self.spinPercentCutMain.value())
                    gate.apply_percent_cut(pct)
                return True
            if getattr(self, 'lag_active', False) or getattr(self, 'dupe_active', False):
                try:
                    self._stop_ics_lag_gate(join_timeout=0.08)
                except Exception:
                    pass
                gate = IcsWinDivertLagGate(ip)
                gate.start(direction=direction)
                self._ics_lag_gate = gate
                if getattr(self, 'lag_active', False) and not getattr(
                    self, '_lag_in_allow_phase', False
                ):
                    gate.pause_connection()
                return True
        if gate is not None:
            self._stop_ics_lag_gate(join_timeout=0.5)
        gate = IcsWinDivertLagGate(ip)
        gate.start(direction=direction)
        self._ics_lag_gate = gate
        if getattr(self, 'lag_active', False) and not getattr(
            self, '_lag_in_allow_phase', False
        ):
            gate.pause_connection()
        if hasattr(gate, 'set_victim_ip'):
            gate.set_victim_ip(ip)
        if not getattr(self, 'lag_active', False):
            self._schedule_ics_windivert_traffic_check(ip)
        return True

    def _apply_ics_client_block(
        self, device, direction, *, for_dupe: bool = False, for_lag: bool = False
    ) -> bool:
        """
        ICS client impairment (all lag methods): pause connection in WinDivert.

        Used for Kill, Dupe, Lag Switch block phase, and firewall fallback avoidance — not ARP MITM.
        Lag Switch uses WinDivert pause only — do not mirror Kill into killer.killed / killed_devices.
        """
        if not clumsy_ics_use_firewall_only(device, self.scanner):
            return False
        device = self._ics_device_with_resolved_ip(device)
        ip = self._ics_hotspot_victim_ip(
            device,
            lag=for_lag,
            dupe=for_dupe,
        ) or clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
            device.get('ip') or ''
        ).strip()
        if ip:
            device['ip'] = ip
        self.killer.disable_percent_cut(device['mac'])
        if device['mac'] in self.killer.killed and not for_dupe and not for_lag:
            release_ics_victim_block(self.scanner, self.killer, device)
        if clumsy_ics_lag_can_use_windivert(device, self.scanner):
            try:
                self._ics_quiesce_killer_mitm(device)
                if self._ensure_ics_lag_gate(device, direction):
                    gate = self._ics_lag_gate
                    if gate is not None:
                        gate.clear_shaping()
                        if hasattr(gate, 'pause_connection'):
                            gate.pause_connection()
                        else:
                            gate.set_blocking(True, mode='pause')
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
                        layers = gate.active_layers if gate is not None else ()
                        cap = getattr(gate, '_capture_desc', '?')
                        ifidx = 0
                        try:
                            from tools.clumsy_inline import clumsy_ics_downstream_ifidx

                            ifidx = clumsy_ics_downstream_ifidx()
                        except Exception:
                            pass
                        self.log(
                            f'Hotspot pause on {ip} (WinDivert {cap} ifIdx={ifidx} '
                            f'layers {layers})',
                            UI_LOG_VICTIM_BLOCK_FG,
                        )
                    return True
            except OSError as exc:
                detail = clumsy_windivert_probe_detail(ip)
                self.log(
                    f'WinDivert lag failed for {ip}: {exc} [{detail}]',
                    'red',
                )
        else:
            self.log(
                'Hotspot lag needs WinDivert: '
                + clumsy_windivert_unavailable_reason(device),
                'red',
            )
        self._stop_ics_lag_gate()
        self.log(
            'Kill/lag on hotspot needs WinDivert — firewall rules usually do not affect the PS5.',
            'red',
        )
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(device['mac'])
        self._updateKillButtonState()
        return False

    def _clear_ics_client_block(self, device, *, pause_only: bool = False) -> bool:
        if not clumsy_ics_use_firewall_only(device, self.scanner):
            return False
        mac = str(device.get('mac') or '').strip()
        windivert = clumsy_ics_lag_can_use_windivert(device, self.scanner)
        if windivert:
            if pause_only:
                self._ics_unpause_victim(device)
            else:
                self._release_ics_windivert_block(device, heal=True)
        else:
            self._ics_unpause_victim(device)
            if not pause_only:
                victim = self._victim_record_for_mac(mac) or device
                try:
                    release_ics_victim_block(self.scanner, self.killer, victim)
                except Exception:
                    pass
                try:
                    unblock_ip(device['ip'])
                except Exception:
                    pass
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

    def _finish_dupe_ics_teardown_net(self, device) -> bool:
        if not isinstance(device, dict) or not clumsy_ics_use_firewall_only(device, self.scanner):
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

    def _apply_victim_block(self, device, direction, **ics_block_kw) -> bool:
        if clumsy_ics_use_firewall_only(device, self.scanner):
            return self._apply_ics_client_block(device, direction, **ics_block_kw)
        self._ensure_network_context_for_victim(device)
        self.killer.disable_percent_cut(device['mac'])
        if device['mac'] not in self.killer.killed:
            self.killer.kill(device)
        iface = self.scanner.iface.name if self.scanner.iface else 'en0'
        block_ip(iface, device['ip'], direction)
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(device['mac'])
        self._updateKillButtonState()
        return True

    def _clear_victim_block(self, device):
        if self._clear_ics_client_block(device):
            return
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

    def _pump_gui_until(self, pred, timeout_ms: int) -> bool:
        """
        Wait for pred() while processing Qt events. Used instead of concurrent.futures.wait
        / Future.result on the GUI thread — those block the event loop so QueuedConnection
        completion slots never run until the wait ends (minutes of apparent freeze).
        """
        try:
            if pred():
                return True
        except Exception:
            return False
        timer = QTimer(self)
        timer.setInterval(15)
        loop = QEventLoop(self)
        el = QElapsedTimer()
        el.start()

        def tick():
            try:
                done = pred()
            except Exception:
                done = True
            if done or el.elapsed() >= timeout_ms:
                timer.stop()
                loop.quit()

        timer.timeout.connect(tick)
        timer.start()
        tick()
        loop.exec_()
        try:
            return bool(pred())
        except Exception:
            return False

    def _drain_dupe_async_network(self, max_wait_ms: int = 120_000):
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
                    if not self._finish_dupe_ics_teardown(device, prev_mac):
                        self._clear_victim_block(device)
                        self._schedule_dupe_off_reinforce(prev_mac, device)
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
            self._pump_gui_until(lambda: fut.done(), 120_000)
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
        self.lblDupeCountdownMain.setVisible(False)
        self.lblDupeCountdownMain.setText('')
        dlg = getattr(self, 'dupe_switch_dialog', None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg.refresh_toggle_state()
            except Exception:
                pass

    def _drop_lag_restoring_banner(self):
        """Clear lag stop restoring flags after teardown (Kill UI / dialog)."""
        self._lag_restoring_after_stop = False
        self._lag_restoring_mac = None
        dlg = getattr(self, 'lag_switch_dialog', None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg.refresh_toggle_state()
            except Exception:
                pass

    def _flush_pending_dupe_clear_sync(self, max_wait_ms: int = 120_000):
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
        device = self._get_device_by_mac(prev_mac) or snap
        if not device or device.get('mac') != prev_mac:
            self._sync_killed_devices()
            self._drop_dupe_restoring_banner()
            return
        try:
            if not self._finish_dupe_ics_teardown(device, prev_mac):
                self._clear_victim_block(device)
                self._schedule_dupe_off_reinforce(prev_mac, device)
        except Exception:
            pass
        self._sync_killed_devices()
        self._drop_dupe_restoring_banner()

    def _do_deferred_dupe_clear(self):
        """Teardown unblock_ip off the GUI thread; unkill/reinforce on the main thread."""
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
        device = self._get_device_by_mac(prev_mac) or snap
        if not device or device.get('mac') != prev_mac:
            self._sync_killed_devices()
            self._drop_dupe_restoring_banner()
            return
        if clumsy_ics_use_firewall_only(device, self.scanner):
            snap = dict(device)

            def _ics_teardown_done() -> None:
                if snap.get('mac') != prev_mac:
                    self._drop_dupe_restoring_banner()
                    return
                self._finish_dupe_ics_teardown_ui(snap)

            self._run_on_flow_net_thread(
                lambda: self._finish_dupe_ics_teardown_net(snap),
                main_after=_ics_teardown_done,
            )
            return
        ip = device.get('ip') or ''
        ex = getattr(self, '_dupe_net_executor', None)
        if ex is None:
            try:
                self._clear_victim_block(device)
                self._schedule_dupe_off_reinforce(prev_mac, device)
            except Exception:
                pass
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
        snap = dict(device)

        def _ics_teardown_done() -> None:
            if snap.get('mac') != prev_mac:
                self._drop_dupe_restoring_banner()
                return
            self._finish_dupe_ics_teardown_ui(snap)

        try:
            if clumsy_ics_use_firewall_only(snap, self.scanner):
                self._run_on_flow_net_thread(
                    lambda: self._finish_dupe_ics_teardown_net(snap),
                    main_after=_ics_teardown_done,
                )
                return
            if not self._finish_dupe_ics_teardown(snap, prev_mac):
                self._clear_victim_block(snap)
                self._schedule_dupe_off_reinforce(prev_mac, snap)
        except Exception:
            pass
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(prev_mac)
        self._updateKillButtonState()
        self._drop_dupe_restoring_banner()

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
        self.lblDupeCountdownMain.setVisible(False)
        self.lblDupeCountdownMain.setText('')

    def _apply_dupe_deferred(self):
        """Kill on main thread; block_ip in worker; stopDupe scheduled for remaining time after block."""
        dev = self._dupe_arm_device
        self._dupe_arm_device = None
        if not dev or not self.dupe_active or self.dupe_device_mac != dev.get('mac'):
            return
        direction = getattr(self, '_dupe_arm_direction', 'both')
        ex = getattr(self, '_dupe_net_executor', None)
        try:
            if clumsy_ics_use_firewall_only(dev, self.scanner):
                if self._apply_ics_client_block(dev, direction, for_dupe=True):
                    self._arm_dupe_burst_wall_clock()
                    self._start_dupe_timers_after_network_ready()
                    return
                self.dupe_active = False
                self.dupe_device_mac = None
                self._abort_dupe_apply_failed()
                self.btnDupe.setText('Dupe')
                self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
                self._ics_emergency_release(dev, heal=False)
                reason = clumsy_windivert_unavailable_reason(dev)
                self.log(
                    f'Dupe on hotspot needs WinDivert (run ZubCut as Administrator). {reason}',
                    'red',
                )
                self._refresh_flow_toggle_ui()
                self._repaint_all_table_rows_for_hover()
                return
            self._arm_dupe_burst_wall_clock()
            self._ensure_network_context_for_victim(dev)
            self.killer.disable_percent_cut(dev['mac'])
            if dev['mac'] not in self.killer.killed:
                self.killer.kill(dev)
            iface = self.scanner.iface.name if self.scanner.iface else 'en0'
            if ex is None:
                exc = _dupe_net_run_block(iface, dev['ip'], direction)
                if exc is not None:
                    raise exc
                self._sync_killed_devices()
                self._refresh_table_row_for_mac(dev['mac'])
                self._updateKillButtonState()
                self._start_dupe_timers_after_network_ready()
                return
            self._dupe_block_ctx = (dev, direction)
            self._dupe_block_apply_pending = True
            fut = ex.submit(_dupe_net_run_block, iface, dev['ip'], direction)
            self._dupe_block_future = fut

            def _done(_f):
                QMetaObject.invokeMethod(self, '_slot_finish_dupe_block', Qt.QueuedConnection)

            fut.add_done_callback(_done)
        except Exception as exc:
            self.dupe_active = False
            self.dupe_device_mac = None
            self._dupe_block_apply_pending = False
            self._dupe_block_ctx = None
            self._dupe_block_future = None
            self._abort_dupe_apply_failed()
            self.btnDupe.setText('Dupe')
            self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
            try:
                if clumsy_ics_use_firewall_only(dev, self.scanner):
                    self._ics_emergency_release(dev, heal=True)
                else:
                    self._clear_victim_block(dev)
            except Exception:
                pass
            self.log(f'Dupe failed to start: {exc}', 'red')
            self._refresh_flow_toggle_ui()
            self._repaint_all_table_rows_for_hover()

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
            self._abort_dupe_apply_failed()
            self.btnDupe.setText('Dupe')
            self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
            try:
                if clumsy_ics_use_firewall_only(dev, self.scanner):
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

    def _lag_ics_windivert_active(self, device) -> bool:
        return bool(
            isinstance(device, dict)
            and clumsy_ics_use_firewall_only(device, self.scanner)
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

    def _lag_ics_resume_allow_phase(self, device) -> None:
        """
        Allow window on hotspot: resume WinDivert pause in-place (fast lag cycles).
        Never tear down the gate here — that breaks allow timing and feels like full Kill.
        """
        if not isinstance(device, dict):
            return
        if not clumsy_ics_use_firewall_only(device, self.scanner):
            self._clear_victim_block(device)
            return
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
        if ip:
            try:
                unblock_ip(ip)
            except Exception:
                pass

    def _lag_apply_allow_phase_sync(self, device) -> None:
        """Main-thread allow: must run immediately so a queued block job cannot skip release."""
        if not self.lag_active or not isinstance(device, dict):
            return
        self._lag_bump_phase_seq()
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
            return 'Time left: 0.0 s'
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
        rem = self.lag_remaining_ms()
        allow = bool(getattr(self, '_lag_in_allow_phase', False))
        if rem is not None and rem <= 0:
            self.lblLagCountdownMain.setVisible(True)
            self._set_countdown_label(self.lblLagCountdownMain, 'Time left: 0.0 s')
            dlg = getattr(self, 'lag_switch_dialog', None)
            if dlg is not None and dlg.isVisible():
                try:
                    dlg.set_lag_countdown(0, allow)
                except Exception:
                    pass
            # Backup when the single-shot phase timer fails to fire (stuck block).
            self._lag_phase_end_timer.stop()
            if not getattr(self, '_lag_phase_advance_pending', False):
                self._lag_do_phase_advance(force=True)
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
        self._lag_bump_phase_seq()
        self._lag_in_allow_phase = False
        self._sync_lag_timing_values_from_ui()
        block_ms = max(1, int(self.lag_block_ms))
        self._lag_schedule_phase(block_ms)
        self._arm_lag_phase_countdown()
        try:
            self._lag_apply_block(device)
        except Exception:
            pass
        mac = str(device.get('mac') or '').strip()
        if mac:
            self._refresh_table_row_for_mac(mac, device.get('ip'))

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
        self._lag_apply_allow_phase_sync(device)
        try:
            self._lag_ics_set_paused(device, False)
        except Exception:
            pass
        self._lag_ics_force_unpause()
        mac = str(device.get('mac') or '').strip()
        if mac:
            self._refresh_table_row_for_mac(mac, device.get('ip'))

    def _lag_apply_block(self, device):
        """Block phase: WinDivert pause in-place when possible (fast lag cycles on hotspot)."""
        try:
            self._ics_quiesce_killer_mitm(device)
        except Exception:
            pass
        if clumsy_ics_use_firewall_only(device, self.scanner):
            if self._lag_ics_windivert_active(device) and self._lag_ics_set_paused(device, True):
                mac = str(device.get('mac') or '').strip()
                if mac:
                    self._refresh_table_row_for_mac(mac, device.get('ip'))
                return
            self._apply_ics_client_block(device, self.lag_direction, for_lag=True)
        else:
            self._apply_victim_block(device, self.lag_direction, for_lag=True)

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
            return dict(snap) if snap else None
        if not snap:
            return dict(live)
        merged = dict(live)
        lip = (live.get('ip') or '').strip()
        sip = (snap.get('ip') or '').strip()
        if (not lip) and sip:
            merged['ip'] = sip
        return merged

    def stopLagSwitch(self, refresh_dialog=True):
        if not self.lag_active:
            self._ics_teardown_gate_if_idle()
            return
        prev_mac = self.lag_device_mac
        snap = getattr(self, '_lag_device_snapshot', None)
        # Stop phase timer before clearing lag_active so a tick cannot re-block.
        self._lag_phase_end_timer.stop()
        self._lag_phase_advance_pending = False
        self._stop_lag_countdown()
        self._cancel_lag_block_reassert()
        device = self._lag_resolved_victim()

        # Instant resume (same path as Kill/Dupe OFF) — do not defer with QTimer.singleShot.
        if device:
            try:
                if clumsy_ics_use_firewall_only(device, self.scanner):
                    self._ics_emergency_release(device, heal=True)
                else:
                    self._lag_ics_set_paused(device, False)
                    self._clear_ics_client_block(device, pause_only=True)
                    ip = (device.get('ip') or '').strip()
                    if ip and _is_valid_ip(ip):
                        try:
                            unblock_ip(ip)
                        except Exception:
                            pass
                    victim = self._victim_record_for_mac(device.get('mac') or '') or device
                    if victim and victim.get('mac') not in self.killer.killed:
                        try:
                            self.killer.unkill(victim)
                        except Exception:
                            pass
            except Exception:
                self._lag_ics_force_unpause()
        else:
            self._ics_teardown_gate_if_idle(prev_mac)

        self.lag_active = False
        self.lag_device_mac = None
        self.lag_device_ip = None
        self._lag_in_allow_phase = False
        self._lag_device_snapshot = None
        self._lag_restoring_after_stop = False
        self._lag_restoring_mac = None
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

    def startDupe(self, device, duration_ms, direction):
        if not _is_valid_ip(device.get('ip') or ''):
            self.log('Target has no IP yet — cannot start dupe.', 'red')
            return
        if self._toggle_start_blocked('dupe'):
            return
        self.stopLagSwitch(refresh_dialog=True)
        self.stopDupe(refresh_dialog=False, log=False)
        self._flush_pending_dupe_clear_sync()
        self._drop_dupe_restoring_banner()
        self._dupe_arm_timer.stop()
        try:
            self._dupe_arm_timer.timeout.disconnect()
        except TypeError:
            pass
        self.dupe_device_mac = device['mac']
        self.dupe_device_ip = device.get('ip')
        self.dupe_direction = direction
        self.dupe_duration_ms = duration_ms
        self._dupe_end_mono = None
        self.dupe_active = True
        self.btnDupe.setText('■ DUPE')
        self.btnDupe.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        dir_text = {'both': 'all', 'in': 'incoming', 'out': 'outgoing'}[direction]
        self.log(f'Dupe: {duration_ms}ms ({dir_text}), then full stop', UI_LOG_VICTIM_BLOCK_FG)
        self._dupe_arm_device = dict(device)
        self._dupe_arm_direction = direction
        self._refresh_flow_toggle_ui()
        self._repaint_all_table_rows_for_hover()
        self._dupe_arm_timer.timeout.connect(self._apply_dupe_deferred, Qt.UniqueConnection)
        self._dupe_arm_timer.start(0)

    def dupe_remaining_ms(self):
        if not self.dupe_active:
            return None
        end = getattr(self, '_dupe_end_mono', None)
        if end is None:
            return int(self.dupe_duration_ms)
        return max(0, int((end - time.monotonic()) * 1000))

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
            self.lblDupeCountdownMain.setVisible(True)
            self._set_countdown_label(self.lblDupeCountdownMain, 'Time left: 0 s')
            if not getattr(self, '_dupe_finish_from_countdown_pending', False):
                self._dupe_finish_from_countdown_pending = True
                QTimer.singleShot(0, partial(self._dupe_finish_from_countdown))
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
        QTimer.singleShot(0, partial(self._dupe_finish_from_countdown, 'Dupe finished'))

    def _dupe_finish_from_countdown(self, log_message='Dupe finished'):
        self._dupe_countdown_timer.stop()
        self.stopDupe(True, True, log_message)

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
        if not was_active:
            self.lblDupeCountdownMain.setVisible(False)
            self.lblDupeCountdownMain.setText('')
            return
        self._dupe_restoring_after_stop = True
        self._dupe_restoring_mac = prev_mac
        self._dupe_restoring_ip = prev_ip
        # Idle chrome immediately; firewall/ARP finish asynchronously (_do_deferred_dupe_clear).
        self.lblDupeCountdownMain.setVisible(False)
        self.lblDupeCountdownMain.setText('')
        # Mark inactive after timers are stopped so _tick cannot race with teardown.
        self.dupe_active = False
        self.dupe_device_mac = None
        self.dupe_device_ip = None
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
        self._drain_dupe_block_if_needed()
        live = self._get_device_by_mac(prev_mac) if prev_mac else None
        arm_ok = arm_snap if (isinstance(arm_snap, dict) and arm_snap.get('mac') == prev_mac) else None
        if live and arm_ok:
            snap = dict(live)
            lip = (live.get('ip') or '').strip()
            sip = (arm_ok.get('ip') or '').strip()
            if (not lip) and sip:
                snap['ip'] = sip
        elif live:
            snap = dict(live)
        elif arm_ok:
            snap = dict(arm_ok)
        else:
            snap = None
        if snap and clumsy_ics_use_firewall_only(snap, self.scanner):
            self._dupe_pending_clear = (prev_mac, snap)
            try:
                self._dupe_deferred_clear_timer.timeout.disconnect()
            except TypeError:
                pass
            self._dupe_deferred_clear_timer.timeout.connect(
                self._do_deferred_dupe_clear, Qt.UniqueConnection
            )
            self._dupe_deferred_clear_timer.start(0)
            return
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
                try:
                    if clumsy_ics_use_firewall_only(dev, self.scanner):
                        self._ics_apply_percent_cut_windivert(dev, pct)
                    else:
                        allow_pct = max(0, 100 - pct)
                        self._ensure_network_context_for_victim(dev)
                        self.killer.apply_percent_cut(dev, pass_percent=allow_pct)
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
        return {
            'kill': 'Kill',
            'lag': 'Lag Switch',
            'dupe': 'Dupe',
            'pctcut': 'Percent Cut',
            'mitmshape': 'MITM shaping',
        }.get(kind, kind)

    def _active_toggle_kind(self):
        if self.lag_active and self.lag_device_mac:
            return 'lag'
        if self.dupe_active and self.dupe_device_mac:
            return 'dupe'
        if self.mitm_shaping_active and self.mitm_shaping_mac:
            return 'mitmshape'
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
        current_ui_on = self._kill_ui_shows_on(mac, device.get('ip'), device)
        if not current_ui_on and len(active_explicit) == 1 and active_explicit[0] != row_pk:
            # Selection drifted to a different row while one kill victim is active.
            victim = self._device_for_kill_profile(active_explicit[0])
            if victim:
                device = victim
                mac = device['mac']
            current_ui_on = self._kill_ui_shows_on(mac, device.get('ip'), device)
        next_state = not current_ui_on
        if next_state and self._toggle_start_blocked('kill'):
            return
        if next_state and clumsy_mode_enabled():
            resolved = clumsy_ics_resolve_victim_ip(device, self.scanner)
            prefix = clumsy_ics_downstream_prefix()
            if resolved and not victim_on_clumsy_ics_subnet(resolved):
                self.log(
                    f'PS5 is on {resolved or device.get("ip")} — Clumsy hotspot expects '
                    f'{prefix}x. Connect the PS5 to PC Mobile Hotspot and rescan.',
                    'red',
                )
                return
        self._set_killed_profile(device, next_state)
        self._updateKillButtonState()
        self._repaint_all_table_rows_for_hover()
        try:
            app = QApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.ExcludeUserInputEvents)
        except Exception:
            pass
        dev = dict(device)
        on = next_state
        src = source
        self._run_kill_command(mac, dev, turn_on=on, source=src)

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
            if self.mitm_shaping_active:
                self.stop_mitm_shaping(log=False)
                self._await_mitm_teardown_thread()
            if self.lag_active and self.lag_device_mac == mac:
                self.stopLagSwitch(refresh_dialog=True)
            if self.dupe_active and self.dupe_device_mac == mac:
                self.stopDupe(log=False)
                self._flush_pending_dupe_clear_sync()
            if self._kill_ui_shows_on(mac, device.get('ip'), device):
                dev = dict(device)
                self._run_kill_command(mac, dev, turn_on=False, source='pctcut_auto_off_kill')
            pct = self._clamp_percent(self.spinPercentCutMain.value())
            allow_pct = max(0, 100 - pct)
            if clumsy_ics_use_firewall_only(device, self.scanner):
                if not clumsy_ics_lag_can_use_windivert(device, self.scanner):
                    self.log(
                        'Percent Cut on hotspot needs WinDivert: '
                        + clumsy_windivert_unavailable_reason(device),
                        'red',
                    )
                    return
                resolved = clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
                    device.get('ip') or ''
                ).strip()
                if not victim_on_clumsy_ics_subnet(resolved):
                    self.log(
                        'Percent Cut needs the PS5 on the hotspot subnet (192.168.137.x). '
                        'Connect the console to PC Mobile Hotspot, then rescan.',
                        'red',
                    )
                    return
                if not self._ics_apply_percent_cut_windivert(device, pct):
                    self.log(
                        'Percent Cut needs WinDivert (run as Administrator).',
                        'red',
                    )
                    return
                resolved_ip = self._ics_hotspot_victim_ip(device, pctcut=True)
            else:
                self._ensure_network_context_for_victim(device)
                self.killer.apply_percent_cut(device, pass_percent=allow_pct)
                resolved_ip = clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
                    device.get('ip') or ''
                ).strip()
            self.percent_cut_active = True
            self.percent_cut_device_mac = mac
            self.percent_cut_device_ip = resolved_ip
            self.log(
                f'Percent Cut ON for {resolved_ip or device["ip"]}: {pct}% cut ({allow_pct}% allowed)',
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
        self.percent_cut_device_ip = None
        victim = self._victim_record_for_mac(prev_mac) or self._get_device_by_mac(prev_mac)
        if victim:
            try:
                if clumsy_ics_lag_can_use_windivert(victim, self.scanner):
                    gate = getattr(self, '_ics_lag_gate', None)
                    if gate is not None:
                        try:
                            gate.apply_percent_cut(0)
                        except Exception:
                            pass
                    if not self._ics_windivert_busy(prev_mac):
                        self._stop_ics_lag_gate()
                else:
                    self._ensure_network_context_for_victim(victim)
                    self.killer.disable_percent_cut(prev_mac)
                    self.killer.unkill(victim)
                    self.killer.reinforce_restore(victim)
                    pct_off_seq = self._bump_flow_off_intent('pctcut', prev_mac)
                    self._schedule_flow_off_reinforce('pctcut', prev_mac, pct_off_seq, 25, victim)
                    self._schedule_flow_off_reinforce('pctcut', prev_mac, pct_off_seq, 90, victim)
                    self._schedule_flow_off_reinforce('pctcut', prev_mac, pct_off_seq, 200, victim)
            except Exception:
                pass
        if log and victim:
            self.log('Percent Cut OFF for ' + victim['ip'], UI_LOG_RESTORE_FG)
        self._refresh_flow_toggle_ui()
        self.showDevices()

    def _refresh_advanced_lag_mitm_if_visible(self) -> None:
        dlg = getattr(self, 'advanced_lag_settings_dialog', None)
        if dlg is not None and dlg.isVisible():
            try:
                dlg._refresh_mitm_status()
            except Exception:
                pass

    def _mitm_adv_sched_record(self, du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, gates=None):
        from tools import mitm_adv_sched

        g = gates if gates is not None else (1.0, 1.0, 1.0, 1.0)
        self._mitm_adv_last_sched = mitm_adv_sched.sched_apply_tuple(
            du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, g
        )

    def _mitm_adv_get(self, key: str, default=None):
        """Scheduler reads live Advanced Lag dialog UI when open, else saved settings."""
        dlg = getattr(self, 'advanced_lag_settings_dialog', None)
        if dlg is not None and getattr(dlg, '_chk_adv_delay_on', None) is not None:
            try:
                return dlg.mitm_adv_settings_get(key, default)
            except Exception:
                pass
        return get_settings(key, default)

    def _reset_mitm_adv_sched_clock(self, row_prefix: str | None = None) -> None:
        """Restart timer phase origin for one impairment row, or all rows."""
        from tools import mitm_adv_sched

        now = mitm_adv_sched.monotonic_now()
        if row_prefix:
            self._mitm_adv_row_t0[str(row_prefix)] = now
        else:
            self._mitm_adv_row_t0 = {p: now for p in mitm_adv_sched.ROW_PREFIXES}
            self._mitm_adv_sched_t0 = now
        self._mitm_adv_last_sched = None

    def _start_mitm_adv_schedule(self):
        t = getattr(self, '_mitm_adv_sched_timer', None)
        if t is not None and getattr(self, 'mitm_shaping_active', False) and not t.isActive():
            t.start()

    def _stop_mitm_adv_schedule(self):
        t = getattr(self, '_mitm_adv_sched_timer', None)
        if t is not None:
            t.stop()
        self._mitm_adv_last_sched = None

    def _mitm_adv_schedule_tick(self):
        if not getattr(self, 'mitm_shaping_active', False):
            self._stop_mitm_adv_schedule()
            return
        if getattr(self, 'percent_cut_active', False):
            self._stop_mitm_adv_schedule()
            return
        if getattr(self, 'lag_active', False) or getattr(self, 'dupe_active', False):
            return
        from tools import mitm_adv_sched

        now = mitm_adv_sched.monotonic_now()
        t0 = float(getattr(self, '_mitm_adv_sched_t0', 0.0) or 0.0)
        if t0 <= 0.0:
            self._reset_mitm_adv_sched_clock()
            t0 = float(self._mitm_adv_sched_t0)
        row_t0 = dict(getattr(self, '_mitm_adv_row_t0', None) or {})
        du, dd, ju, jd, cu, cd, lu, ld, gates = mitm_adv_sched.gated_mitm_params(
            now, t0, self._mitm_adv_get, row_t0
        )
        prev = getattr(self, '_mitm_adv_last_sched', None)
        cur_tuple = mitm_adv_sched.sched_apply_tuple(
            du, dd, ju, jd, cu, cd, lu, ld, gates
        )
        if prev == cur_tuple:
            return
        self.start_mitm_shaping_from_advanced(
            du, dd, ju, jd, cu, cd, lu, ld, sched_tick=True
        )

    def _mitm_adv_apply_sched_tick(
        self,
        device,
        mac: str,
        *,
        du: int,
        dd: int,
        ju: int,
        jd: int,
        cu_mbps: float,
        cd_mbps: float,
        lu: int,
        ld: int,
        adv_gates,
        use_wd: bool,
    ) -> bool:
        """Apply one scheduler tick without full MITM restart. Returns True if handled."""
        if getattr(self, 'lag_active', False) or getattr(self, 'dupe_active', False):
            self._refresh_advanced_lag_mitm_if_visible()
            return True
        if use_wd and clumsy_ics_use_firewall_only(device, self.scanner):
            if self._ics_apply_advanced_shaping_windivert(
                device,
                du=du,
                dd=dd,
                ju=ju,
                jd=jd,
                lu=lu,
                ld=ld,
                cu_mbps=cu_mbps,
                cd_mbps=cd_mbps,
            ):
                self._mitm_shaping_backend = 'windivert'
                self._ics_windivert_shaper = self._ics_lag_gate
                self._mitm_adv_sched_record(
                    du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
                )
                self._start_mitm_adv_schedule()
                self._refresh_advanced_lag_mitm_if_visible()
            return True
        backend = getattr(self, '_mitm_shaping_backend', None)
        if backend == 'windivert' and use_wd and self._ics_lag_gate is not None:
            if self._ics_apply_advanced_shaping_windivert(
                device,
                du=du,
                dd=dd,
                ju=ju,
                jd=jd,
                lu=lu,
                ld=ld,
                cu_mbps=cu_mbps,
                cd_mbps=cd_mbps,
            ):
                self._mitm_adv_sched_record(
                    du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
                )
                self._start_mitm_adv_schedule()
                self._refresh_advanced_lag_mitm_if_visible()
                return True
        if backend == 'windivert' and not use_wd and self._ics_lag_gate is not None:
            try:
                self._ics_lag_gate.clear_shaping()
                self._ics_lag_gate.prepare_stop()
                self._stop_ics_lag_gate()
            except Exception:
                pass
            self._ics_windivert_shaper = None
            self._mitm_shaping_backend = 'forwarder'
            backend = 'forwarder'
        if backend == 'forwarder':
            if clumsy_ics_use_firewall_only(device, self.scanner):
                self._refresh_advanced_lag_mitm_if_visible()
                return True
            try:
                self._ensure_network_context_for_victim(device)
                self.killer.apply_link_shaping(
                    device,
                    delay_ms_out=du,
                    delay_ms_in=dd,
                    jitter_ms_out=ju,
                    jitter_ms_in=jd,
                    loss_pct_out=lu,
                    loss_pct_in=ld,
                    max_kbps_out=cu_mbps * 1000.0,
                    max_kbps_in=cd_mbps * 1000.0,
                )
            except Exception as exc:
                self.log(f'MITM shaping update failed: {exc}', 'red')
                self._refresh_advanced_lag_mitm_if_visible()
                return True
            self._mitm_adv_sched_record(
                du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
            )
            self._start_mitm_adv_schedule()
            self._refresh_advanced_lag_mitm_if_visible()
            return True
        return False

    def start_mitm_shaping_from_advanced(
        self,
        delay_up,
        delay_down,
        jitter_up=0,
        jitter_down=0,
        cap_up=0.0,
        cap_down=0.0,
        loss_up=0,
        loss_down=0,
        *,
        sched_tick=False,
    ):
        """Forwarder shaping from Advanced Lag (delay, jitter, caps, loss)."""
        if not sched_tick:
            self._await_mitm_teardown_thread()
        if not self.connected():
            self._refresh_advanced_lag_mitm_if_visible()
            return
        if self._toggle_start_blocked('mitmshape'):
            self._refresh_advanced_lag_mitm_if_visible()
            return
        # While shaping is already running, apply parameter changes to the shaped device even if
        # the table selection moved (otherwise toggles in Advanced Lag appear to do nothing).
        shaping_mac = self.mitm_shaping_mac if self.mitm_shaping_active else None
        if shaping_mac:
            selected = self._get_selected_device()
            if selected is not None and selected.get('mac') == shaping_mac:
                device = selected
            else:
                device = self._victim_record_for_mac(shaping_mac) or self._get_device_by_mac(
                    shaping_mac
                )
            if not device:
                self.log(
                    'The device being shaped is no longer in the list — use Stop, turn Kill off, or rescan.',
                    'red',
                )
                self._refresh_advanced_lag_mitm_if_visible()
                return
        else:
            device = self._get_selected_device()
            if not device:
                self.log('Select a device in the list first.', 'red')
                self._refresh_advanced_lag_mitm_if_visible()
                return
        if device.get('admin'):
            self.log('Cannot shape admin device', UI_LOG_VICTIM_BLOCK_FG)
            self._refresh_advanced_lag_mitm_if_visible()
            return
        mac = device['mac']
        if not _is_valid_ip(device.get('ip') or ''):
            self.log('Target has no IP yet — cannot start shaping.', 'red')
            self._refresh_advanced_lag_mitm_if_visible()
            return

        from tools import mitm_adv_sched

        prev_active = self.mitm_shaping_active
        prev_sm = self.mitm_shaping_mac
        if not prev_active or prev_sm != mac:
            self._reset_mitm_adv_sched_clock()
        row_t0 = dict(getattr(self, '_mitm_adv_row_t0', None) or {})
        du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates = mitm_adv_sched.gated_mitm_params(
            mitm_adv_sched.monotonic_now(),
            self._mitm_adv_sched_t0,
            self._mitm_adv_get,
            row_t0,
        )
        du = max(0, int(du))
        dd = max(0, int(dd))
        ju = max(0, int(ju))
        jd = max(0, int(jd))
        cu_mbps = max(0.0, float(cu_mbps))
        cd_mbps = max(0.0, float(cd_mbps))
        lu = max(0, min(100, int(lu)))
        ld = max(0, min(100, int(ld)))
        allow_zero = bool(sched_tick or (prev_active and prev_sm == mac))
        all_zero = (
            du <= 0
            and dd <= 0
            and ju <= 0
            and jd <= 0
            and cu_mbps <= 0
            and cd_mbps <= 0
            and lu <= 0
            and ld <= 0
        )
        if all_zero and not allow_zero:
            if not sched_tick:
                self.log(
                    'Enable at least one effect with non-zero values (delay, jitter, cap, or loss).',
                    'red',
                )
            self._refresh_advanced_lag_mitm_if_visible()
            return

        use_wd = use_windivert_for_advanced_ics_shaping(self.scanner, device)
        if sched_tick and self.mitm_shaping_active and prev_sm == mac and shaping_mac == mac:
            if self._mitm_adv_apply_sched_tick(
                device,
                mac,
                du=du,
                dd=dd,
                ju=ju,
                jd=jd,
                cu_mbps=cu_mbps,
                cd_mbps=cd_mbps,
                lu=lu,
                ld=ld,
                adv_gates=adv_gates,
                use_wd=use_wd,
            ):
                return

        if (
            shaping_mac
            and shaping_mac == mac
            and self.mitm_shaping_active
            and getattr(self, '_mitm_shaping_backend', None) == 'windivert'
            and self._ics_lag_gate is not None
            and use_wd
        ):
            if getattr(self, 'lag_active', False) or getattr(self, 'dupe_active', False):
                self._refresh_advanced_lag_mitm_if_visible()
                return
            if self._ics_apply_advanced_shaping_windivert(
                device,
                du=du,
                dd=dd,
                ju=ju,
                jd=jd,
                lu=lu,
                ld=ld,
                cu_mbps=cu_mbps,
                cd_mbps=cd_mbps,
            ):
                self._mitm_adv_sched_record(
                    du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
                )
                self._start_mitm_adv_schedule()
                self._refresh_advanced_lag_mitm_if_visible()
            return

        self.stopLagSwitch(refresh_dialog=True)
        self.stopDupe(refresh_dialog=False, log=False)
        self._flush_pending_dupe_clear_sync()
        self.stopPercentCut(log=False)

        use_forwarder = True
        self._mitm_shaping_backend = None
        from tools.ics_windivert_shaper import IcsWinDivertShaper

        if use_wd:
            if mac in self.killer.killed:
                try:
                    v0 = self._victim_record_for_mac(mac) or device
                    self.killer.unkill(v0)
                except Exception:
                    pass
            try:
                self.killer.disable_percent_cut(mac)
            except Exception:
                pass
            try:
                if not self._ics_apply_advanced_shaping_windivert(
                    device,
                    du=du,
                    dd=dd,
                    ju=ju,
                    jd=jd,
                    lu=lu,
                    ld=ld,
                    cu_mbps=cu_mbps,
                    cd_mbps=cd_mbps,
                ):
                    raise OSError('WinDivert gate failed')
                self._mitm_shaping_backend = 'windivert'
                use_forwarder = False
            except Exception as exc:
                detail = clumsy_windivert_unavailable_reason(device)
                if clumsy_ics_use_firewall_only(device, self.scanner):
                    self.log(
                        f'Advanced lag WinDivert failed ({exc}) [{detail}]',
                        'red',
                    )
                else:
                    self.log(
                        f'WinDivert shaping failed ({exc}); using MITM forwarder instead.',
                        'red',
                    )
                self._ics_windivert_shaper = None
                if clumsy_ics_use_firewall_only(device, self.scanner):
                    self._refresh_advanced_lag_mitm_if_visible()
                    return

        if use_forwarder:
            if clumsy_ics_use_firewall_only(device, self.scanner):
                if not sched_tick:
                    reason = clumsy_windivert_unavailable_reason(device)
                    self.log(
                        'Advanced lag on PC hotspot needs WinDivert — not ARP Kill/forwarder. '
                        + reason,
                        'red',
                    )
                self._refresh_advanced_lag_mitm_if_visible()
                return
            try:
                self._ensure_network_context_for_victim(device)
                self.killer.apply_link_shaping(
                    device,
                    delay_ms_out=du,
                    delay_ms_in=dd,
                    jitter_ms_out=ju,
                    jitter_ms_in=jd,
                    loss_pct_out=lu,
                    loss_pct_in=ld,
                    max_kbps_out=cu_mbps * 1000.0,
                    max_kbps_in=cd_mbps * 1000.0,
                )
            except Exception as exc:
                self.log(f'MITM shaping failed: {exc}', 'red')
                self._refresh_advanced_lag_mitm_if_visible()
                return
            self._ics_windivert_shaper = None
            self._mitm_shaping_backend = 'forwarder'

        if use_wd and clumsy_ics_use_firewall_only(device, self.scanner):
            resolved_ip = self._ics_hotspot_victim_ip(device, mitmshape=True) or str(
                device.get('ip') or ''
            ).strip()
        else:
            resolved_ip = clumsy_ics_resolve_victim_ip(device, self.scanner) or str(
                device.get('ip') or ''
            ).strip()
        self.mitm_shaping_active = True
        self.mitm_shaping_mac = mac
        self.mitm_shaping_device_ip = resolved_ip
        if self._mitm_shaping_backend == 'forwarder':
            self._set_killed_profile(device, True)
            self._sync_killed_devices()
            set_settings('killed', list(self.killer.killed) * self.remember)
        parts = []
        if du > 0:
            parts.append(f'out delay {du}ms')
        if dd > 0:
            parts.append(f'in delay {dd}ms')
        if ju > 0:
            parts.append(f'out jitter +0–{ju}ms')
        if jd > 0:
            parts.append(f'in jitter +0–{jd}ms')
        if cu_mbps > 0:
            parts.append(f'out cap {cu_mbps:g}Mbps')
        elif bool(get_settings('mitm_adv_cap_on')) and bool(get_settings('mitm_adv_cap_out')):
            parts.append('out cap ∞')
        if cd_mbps > 0:
            parts.append(f'in cap {cd_mbps:g}Mbps')
        elif bool(get_settings('mitm_adv_cap_on')) and bool(get_settings('mitm_adv_cap_in')):
            parts.append('in cap ∞')
        if lu > 0:
            parts.append(f'out loss {lu}%')
        if ld > 0:
            parts.append(f'in loss {ld}%')
        path_note = 'WinDivert ICS' if self._mitm_shaping_backend == 'windivert' else 'MITM'
        if not sched_tick:
            detail = ', '.join(parts) if parts else 'timers / gates (may be off this moment)'
            self.log(
                f'Advanced lag ON ({path_note}) — {detail} — for ' + str(device.get('ip', '')),
                UI_LOG_VICTIM_BLOCK_FG,
            )
        self._mitm_adv_sched_record(
            du, dd, ju, jd, cu_mbps, cd_mbps, lu, ld, adv_gates
        )
        self._start_mitm_adv_schedule()
        self._refresh_flow_toggle_ui()
        self._refresh_advanced_lag_mitm_if_visible()

    def _await_mitm_teardown_thread(self, timeout_s=8.0):
        """Advanced lag OFF runs sniffer teardown off-thread; wait before starting shaping again."""
        t = getattr(self, '_mitm_teardown_thread', None)
        if t is None or not t.is_alive():
            return
        # Avoid threading.Thread.join on the GUI thread — it freezes Qt for up to timeout_s.
        deadline_ms = int(float(timeout_s) * 1000)
        timer = QTimer(self)
        timer.setInterval(25)
        loop = QEventLoop(self)
        el = QElapsedTimer()
        el.start()

        def tick():
            if not t.is_alive() or el.elapsed() >= deadline_ms:
                timer.stop()
                loop.quit()

        timer.timeout.connect(tick)
        timer.start()
        tick()
        loop.exec_()

    def _on_mitm_teardown_finished(self, prev_mac: str, log: bool, log_ip: str, was_windivert: bool, victim_snap):
        self._mitm_teardown_thread = None
        mac = prev_mac or None
        if was_windivert and not self._ics_windivert_busy(mac):
            self._stop_ics_lag_gate()
        if isinstance(victim_snap, dict):
            self._set_killed_profile(victim_snap, False)
        elif mac:
            self._set_killed_profile({'mac': mac, 'ip': log_ip or ''}, False)
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
        if (
            mac
            and isinstance(victim_snap, dict)
            and not was_windivert
        ):
            try:
                mseq = self._bump_flow_off_intent('mitmshape', mac)
                self._schedule_flow_off_reinforce('mitmshape', mac, mseq, 25, victim_snap)
                self._schedule_flow_off_reinforce('mitmshape', mac, mseq, 90, victim_snap)
                self._schedule_flow_off_reinforce('mitmshape', mac, mseq, 200, victim_snap)
            except Exception:
                pass
        self._updateKillButtonState()
        self._refresh_flow_toggle_ui()
        self._refresh_advanced_lag_mitm_if_visible()
        if not log:
            return
        if was_windivert:
            if log_ip:
                self.log(f'MITM shaping OFF for {log_ip} (WinDivert ICS)', UI_LOG_RESTORE_FG)
            elif mac:
                self.log('Advanced lag shaping stopped (WinDivert ICS).', UI_LOG_RESTORE_FG)
        elif log_ip:
            self.log('MITM shaping OFF for ' + str(log_ip), UI_LOG_RESTORE_FG)
        elif mac:
            self.log('Advanced lag shaping stopped (device no longer in list).', UI_LOG_RESTORE_FG)

    def stop_mitm_shaping(self, log=True):
        if not self.mitm_shaping_active:
            return
        self._stop_mitm_adv_schedule()
        self._mitm_adv_row_t0 = {}
        prev_mac = self.mitm_shaping_mac
        backend = getattr(self, '_mitm_shaping_backend', None)
        shaper = getattr(self, '_ics_windivert_shaper', None)

        victim = self._victim_record_for_mac(prev_mac) or self._get_device_by_mac(prev_mac)
        if victim is None and prev_mac:
            victim = (getattr(self.killer, 'killed', None) or {}).get(prev_mac)
        victim_snap = dict(victim) if isinstance(victim, dict) else None

        self.mitm_shaping_active = False
        self.mitm_shaping_mac = None
        self.mitm_shaping_device_ip = None
        self._mitm_shaping_backend = None
        self._ics_windivert_shaper = None

        self._refresh_advanced_lag_mitm_if_visible()

        was_wd = backend == 'windivert' and shaper is not None
        gate = self._ics_lag_gate if was_wd else None

        def _teardown_worker():
            log_ip = ''
            try:
                if prev_mac:
                    try:
                        self.killer.disable_percent_cut(prev_mac)
                    except Exception:
                        pass
                if was_wd and gate is not None:
                    try:
                        gate.clear_shaping()
                        gate.prepare_stop()
                    except Exception:
                        pass
                    if isinstance(victim_snap, dict):
                        log_ip = str(victim_snap.get('ip') or '')
                elif isinstance(victim_snap, dict):
                    try:
                        self._ensure_network_context_for_victim(victim_snap)
                    except Exception:
                        pass
                    try:
                        unblock_ip(victim_snap.get('ip') or '')
                    except Exception:
                        pass
                    try:
                        self.killer.unkill(victim_snap)
                        self.killer.reinforce_restore(victim_snap)
                    except Exception:
                        pass
                    log_ip = str(victim_snap.get('ip') or '')
            finally:
                try:
                    self.mitm_teardown_finished.emit(
                        str(prev_mac or ''),
                        bool(log),
                        log_ip,
                        bool(was_wd),
                        victim_snap,
                    )
                except Exception:
                    pass

        t = threading.Thread(target=_teardown_worker, daemon=True, name='mitm-stop-teardown')
        self._mitm_teardown_thread = t
        t.start()

    def _run_kill_command(self, mac, device, turn_on, source='unknown'):
        """Immediate explicit command path: one click => one kill/unkill command."""
        if turn_on:
            if getattr(self, '_kill_teardown_mac', None) == mac:
                self._kill_teardown_mac = None
                self._kill_teardown_ip = None
        else:
            self._kill_teardown_mac = mac
            self._kill_teardown_ip = device.get('ip')
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
            kill_applied = False
            if turn_on:
                if self.lag_active and self.lag_device_mac == mac:
                    self.stopLagSwitch(refresh_dialog=True)
                if self.dupe_active and self.dupe_device_mac == mac:
                    self.stopDupe(log=False)
                    self._flush_pending_dupe_clear_sync()
                if self.percent_cut_active and self.percent_cut_device_mac == mac:
                    self.stopPercentCut(log=False)
                if self.mitm_shaping_active and self.mitm_shaping_mac == mac:
                    self.stop_mitm_shaping(log=False)
                    self._await_mitm_teardown_thread()
                if not actual_on and device:
                    if not _is_valid_ip(device.get('ip') or ''):
                        self.log('Target has no IP yet — enable sharing and rescan.', 'red')
                    elif clumsy_ics_use_firewall_only(device, self.scanner):
                        kill_applied = bool(self._apply_victim_block(device, 'both'))
                        if kill_applied:
                            self.log('Kill ON for ' + device['ip'], UI_LOG_VICTIM_BLOCK_FG)
                        else:
                            self._ics_emergency_release(device, heal=False)
                            ip = clumsy_ics_resolve_victim_ip(device, self.scanner)
                            detail = clumsy_windivert_probe_detail(ip)
                            self.log(
                                f'Kill failed — WinDivert: {detail}',
                                'red',
                            )
                    else:
                        self._ensure_network_context_for_victim(device)
                        self.killer.disable_percent_cut(mac)
                        self.killer.kill(device)
                        try:
                            iface = self.scanner.iface.name if self.scanner.iface else 'en0'
                            block_ip(iface, device['ip'], 'both')
                        except Exception:
                            pass
                        self.log('Kill ON for ' + device['ip'], UI_LOG_VICTIM_BLOCK_FG)
                        kill_applied = True
            else:
                if self.mitm_shaping_active and self.mitm_shaping_mac == mac:
                    self.stop_mitm_shaping(log=False)
                    self._await_mitm_teardown_thread()
                victim = self._victim_record_for_mac(mac) or device
                if victim:
                    if clumsy_ics_use_firewall_only(victim, self.scanner):
                        self._ics_emergency_release(victim, heal=True)
                    else:
                        try:
                            unblock_ip(victim.get('ip') or '')
                        except Exception:
                            pass
                        self.killer.unkill(victim)
                        self.killer.reinforce_restore(victim)
                        if actual_on:
                            self.killer.reinforce_restore(victim)
                    self.log('Kill OFF for ' + str(victim.get('ip', '')), UI_LOG_RESTORE_FG)
                    # OFF-only delayed reinforcement; guarded by intent_seq so stale callbacks no-op.
                    self._schedule_kill_off_reinforce(mac, next_seq, 25)
                    self._schedule_kill_off_reinforce(mac, next_seq, 100)

            self._set_killed_profile(device, bool(kill_applied) if turn_on else False)
            self._sync_killed_devices()
            set_settings('killed', list(self.killer.killed) * self.remember)
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
        finally:
            if teardown_off and getattr(self, '_kill_teardown_mac', None) == mac:
                self._kill_teardown_mac = None
                self._kill_teardown_ip = None

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
                if clumsy_ics_use_firewall_only(victim, self.scanner):
                    if mac in self.killer.killed:
                        release_ics_victim_block(self.scanner, self.killer, victim)
                    else:
                        return
                    if self._ics_windivert_busy(mac):
                        return
                    try:
                        unblock_ip(victim.get('ip') or '')
                    except Exception:
                        pass
                    self._stop_ics_lag_gate()
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
                if clumsy_ics_use_firewall_only(victim, self.scanner):
                    if mac not in self.killer.killed:
                        return
                    release_ics_victim_block(self.scanner, self.killer, victim)
                    try:
                        unblock_ip(victim.get('ip') or '')
                    except Exception:
                        pass
                    self._stop_ics_lag_gate()
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

    def _get_selected_device(self):
        """Current table row device (toolbar clicks clear selection; currentRow still identifies victim)."""
        row = self.tableScan.currentRow()
        if row < 0 or row >= len(self.scanner.devices):
            return None
        return self.scanner.devices[row]

    def _sync_killed_devices(self):
        """
        Drop Kill-toggle bookkeeping when killer no longer holds this subnet profile.
        Lag/dupe also use killer.killed for ARP — do not mirror that onto every nickname row.
        """
        active_macs = set(self.killer.killed.keys())
        preserve_profiles = set()
        for pk in list(self.killed_devices.keys()):
            if pk in preserve_profiles:
                continue
            mac, _pfx = parse_nickname_profile_key(pk)
            if not mac and '|' not in pk:
                mac = pk
            if not mac:
                self.killed_devices.pop(pk, None)
                continue
            if mac not in active_macs:
                if mac in getattr(self, '_ics_kill_profile_macs', set()):
                    continue
                self.killed_devices[pk] = False
                continue
            if '|' in pk:
                victim = self.killer.killed.get(mac)
                if victim:
                    vpk = nickname_profile_key(mac, victim.get('ip', ''))
                    if pk != vpk:
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
        if base_tip:
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

    def _get_device_by_mac(self, mac, ip=None):
        matches = [d for d in self.scanner.devices if d.get('mac') == mac]
        if not matches:
            return None
        want_ip = (ip or '').strip()
        if want_ip:
            for device in matches:
                if (device.get('ip') or '').strip() == want_ip:
                    return device
        return matches[0]

    def _victim_record_for_mac(self, mac):
        """
        Victim dict for unkill: same MAC as when killed, but IP refreshed from the current scan
        so ARP restore matches the real host after DHCP / rescan.
        """
        if mac in self.killer.killed:
            victim = dict(self.killer.killed[mac])
            fresh = self._get_device_by_mac(mac, victim.get('ip'))
            if fresh:
                victim['ip'] = fresh['ip']
            return victim
        return None

    def _enqueue_kill_off_only(self, mac, device):
        """After lag/dupe stop: execute an explicit OFF command immediately."""
        self._set_killed_profile(device, False)
        self._updateKillButtonState()
        dev = dict(device)
        self._run_kill_command(mac, dev, turn_on=False, source='enqueue_off_only')

