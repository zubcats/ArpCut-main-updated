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
from PyQt5.QtGui import QPixmap, QIcon, QFont, QKeySequence, QBrush, QFontMetrics, QColor, QPalette
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
from gui.logs_window import LogEntry, LogsWindow, log_color_to_hex
from .traffic import Traffic
from .kill_flows import KillFlowsWindow

from networking.scanner import Scanner
from networking.killer import Killer
from networking.nicknames import nickname_profile_key, parse_nickname_profile_key

from tools.qtools import (
    colored_item,
    MsgType,
    Buttons,
    clickable,
    TableRowNoCellFocusDelegate,
    scan_table_item_flags,
    resolve_scan_table_click_row,
)
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
    theme_popup_menu,
)
from gui.impairment_controller import ImpairmentController, toggle_kind_label as _impairment_toggle_kind_label
from gui.impairment_plan import ImpairmentPlanMixin
from gui.impairment_prep import ImpairmentPrepMixin
from gui.impairment_ics_gate import ImpairmentIcsGateMixin
from gui.impairment_blocks import ImpairmentBlocksMixin
from gui.impairment_lag import ImpairmentLagMixin
from gui.impairment_dupe import ImpairmentDupeMixin
from gui.impairment_kill import ImpairmentKillMixin
from gui.impairment_pctcut import ImpairmentPctCutMixin
from gui.impairment_mitm import ImpairmentMitmMixin
from gui.impairment_flow_net import ImpairmentFlowNetMixin
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
from tools.ics_impairment_policy import (
    classify_device_impairment,
    device_row_for_impairment,
    impairment_status_line,
    quiesce_legacy_stack,
    should_restore_remembered_kill,
)
from tools.keybinds import keyseq_from_setting
from tools.branding import (
    load_application_qicon,
    load_shell_window_icon,
    load_tray_window_icon,
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
from tools.crash_feedback import safe_daemon_target
from tools.pfctl import _is_valid_ip, block_ip, unblock_ip


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

    def __init__(self, *, force_refresh: bool = False):
        super().__init__()
        self._force_refresh = bool(force_refresh)

    def run(self):
        from tools.updater_core import get_update_status

        try:
            avail, label = get_update_status(force_refresh=self._force_refresh)
        except Exception:
            return
        # None = indeterminate (API/republish race); keep existing green hint.
        if avail is None:
            return
        self.done.emit(bool(avail), str(label or ''))

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
from gui.impairment_shared import (
    ADMIN_DEVICE_TABLE_ROW_BG,
    ADMIN_DEVICE_TABLE_ROW_FG,
    UI_LOG_VICTIM_BLOCK_FG,
    UI_LOG_RESTORE_FG,
    _DEVICE_ROW_KILL_BG,
    _DEVICE_ROW_KILL_FG,
    _DEVICE_ROW_KILL_HOVER_BG,
    _DEVICE_ROW_KILL_HOVER_FG,
    _DEVICE_ROW_KILL_SELECTED_BG,
    _DEVICE_ROW_KILL_SELECTED_FG,
    _DEVICE_ROW_KILL_SEL_HOVER_BG,
    _DEVICE_ROW_KILL_SEL_HOVER_FG,
    format_countdown_ms,
    _dupe_net_run_unblock,
    _dupe_net_run_block,
    _bg_unblock_ip,
    _bg_block_ip,
    _focus_widget_absorbs_letter_key,
)

# from qt_material import build_stylesheet

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
        if main._toggle_start_blocked('lag', device):
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
        self.dupeSpin.setToolTip(
            'Dupe burst length. Default 5000 ms. '
            'With Logs → Analysis ON, keep ≥ 8000 ms (5s is often too short for DURING).'
        )
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
        if main._toggle_start_blocked('dupe', device):
            return
        ms, direction = self.values()
        main.dupe_duration_ms = ms
        main.dupe_direction = direction
        main.startDupe(device, ms, direction)



class ZubCutApp(
    ImpairmentPlanMixin,
    ImpairmentPrepMixin,
    ImpairmentIcsGateMixin,
    ImpairmentBlocksMixin,
    ImpairmentLagMixin,
    ImpairmentDupeMixin,
    ImpairmentKillMixin,
    ImpairmentPctCutMixin,
    ImpairmentMitmMixin,
    ImpairmentFlowNetMixin,
    FramelessResizableMixin,
    QMainWindow,
    Ui_MainWindow,
):
    """Main ZubCut window (network scan, impairment toggles, Clumsy hotspot path)."""
    mitm_teardown_finished = pyqtSignal(str, bool, str, bool, object)
    flow_net_main_done = pyqtSignal(object)
    # findings list + reason — emitted from PC-readiness worker; always Queued to GUI.
    readiness_pc_done = pyqtSignal(object, str)

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

        # Left status strip (lblleft): elide long lines to fit; full text in Logs window (right-click).
        self._status_strip_plain = None
        self._status_strip_color = 'white'
        self._log_history: list[LogEntry] = []
        self._log_history_max = 500
        self.lblleft.setWordWrap(False)
        self.lblleft.setMaximumHeight(self.lblleft.fontMetrics().height() + 6)
        self.lblleft.setAutoFillBackground(False)
        self.lblleft.setTextFormat(Qt.PlainText)
        self.lblleft.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lblleft.customContextMenuRequested.connect(self._on_status_log_context_menu)
        self.gridLayout.addWidget(self.lblleft, 3, 1, 1, 2)

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
        # Pre-warm the Npcap L2 socket on a background thread so the first Kill ON
        # doesn't wait ~0.5–2 s on conf.L2socket() opening Npcap. Pure no-op on Linux.
        self._schedule_npcap_prewarm('startup')
        self.killed_devices = {}  # profile key (mac|subnet) -> explicit Kill toggle state
        # Immediate visual latch: keep Kill row highlighted between toggle-on click
        # and backend apply completion, even if sync paths briefly clear killed_devices.
        self._kill_pending_profiles = set()
        # Per-MAC intent generation for kill toggle; delayed OFF reinforcement only runs
        # when generation still matches (prevents stale delayed actions from reapplying).
        self._kill_intent_seq = {}
        # Per-flow OFF intent generation (lag/dupe/unkill-all).
        self._flow_off_intent_seq = {}
        # Explicit Kill OFF in flight: ignore killer.killed fallback until _run_kill_command finishes.
        self._kill_teardown_mac = None
        self._kill_teardown_ip = None
        self._impairment = ImpairmentController(
            state_provider=lambda: self,
            killed_profile_on=self._killed_profile_on,
            log=lambda msg, kind: self.log(
                msg,
                UI_LOG_RESTORE_FG if kind == 'restore' else UI_LOG_VICTIM_BLOCK_FG,
            ),
        )
        self.lag_active = False
        self.lag_block_ms = 9000
        self.lag_release_ms = 1500
        self._lag_reassert_gen = 0
        self._lag_phase_seq = 0
        self.lag_device_mac = None
        self.lag_device_ip = None
        self._lag_net_prepared_mac = None
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
        self._impairment_stack_warmed_at = 0.0
        self._lan_impairment_warmed_at = 0.0
        self._impairment_warm_in_flight = False
        self._lag_ics_preblocked = False
        self._lag_lan_preblocked = False
        self._dupe_preblocked = False
        self._last_app_inactive_mono = time.monotonic()
        self._ics_kill_profile_macs: set[str] = set()
        self._selected_impairment_mac: str | None = None
        self._selected_impairment_plan = None
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
        self.readiness_pc_done.connect(self._deliver_pc_readiness_findings)
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
        self._mitm_probe_retried_macs: set[str] = set()
        self._cut_analysis_enabled = False
        self._cut_analysis_gen = 0
        self._cut_analysis_baseline_gen = 0
        self._cut_analysis_baseline = None
        self._cut_analysis_session = None
        self._cut_analysis_baseline_timer = None
        self._idle_mitm_reconcile_timer = QTimer(self)
        self._idle_mitm_reconcile_timer.setInterval(20000)
        self._idle_mitm_reconcile_timer.timeout.connect(
            lambda: self._reconcile_idle_mitm_state(quiet=True)
        )
        self._idle_mitm_reconcile_timer.start()
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
        self._shutting_down = False
        self._lag_start_gen = 0
        self._dupe_start_gen = 0
        self._dupe_armed_ok = False
        self._pctcut_start_gen = 0
        self._pctcut_preapplied = False
        self._pctcut_off_until = 0.0

        # Threading
        self.scan_thread = ScanThread()
        self.scan_thread.thread_finished.connect(self.ScanThread_Reciever)
        self.scan_thread.progress.connect(self.pgbar.setValue, Qt.QueuedConnection)
        self.pgbar.setAttribute(Qt.WA_StyledBackground, True)

        # Update thread disabled for fork
        # self.update_thread = UpdateThread()
        # self.update_thread.thread_finished.connect(self.UpdateThread_Reciever)
        
        # Initialize other sub-windows
        self.settings_window = Settings(self, self.shell_icon)
        self.about_window = About(self, self.shell_icon)
        self.device_window = Device(self, self.shell_icon)
        self.traffic_window = Traffic(self, self.shell_icon)
        self.kill_flows_window = KillFlowsWindow(self, self.shell_icon)
        self.logs_window = LogsWindow(self, self.shell_icon)

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
        self.btnLagSwitch.pressed.connect(lambda: self._shortcut_global_lag(from_button=True))
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
            'Duration/direction controls are always visible below. Shortcut: P. '
            'With Logs → Analysis ON, use at least 8000 ms (8s); 5s is often too short for DURING.'
        )
        self.btnDupe.pressed.connect(lambda: self._shortcut_global_dupe(from_button=True))

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
        self.dupeSpinMain.setToolTip(
            'Dupe burst length. Default 5000 ms. '
            'With Logs → Analysis ON, keep ≥ 8000 ms (5s is often too short for DURING).'
        )
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
        theme_popup_menu(tray_menu)
        tray_menu.addAction(show_option)
        tray_menu.addAction(hide_option)
        tray_menu.addSeparator()
        self.traffic_option = QAction('Kill Flows for Selected', self)
        self.traffic_option.triggered.connect(self.openKillFlows)
        tray_menu.addAction(self.traffic_option)
        tray_menu.addAction(quit_option)
        
        # Parent the tray to the QApplication, not the main window, so teardown order
        # does not drop the icon before hide() runs (reduces ghost icons on Windows).
        self.tray_icon = QSystemTrayIcon(QApplication.instance())
        _tray_icon = load_tray_window_icon()
        if qicon_is_empty(_tray_icon):
            _tray_icon = self.shell_icon
        self.tray_icon.setIcon(_tray_icon)
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
            self.kill_flows_window,
            self.logs_window,
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
        hex_color = log_color_to_hex(color)
        # Global QSS sets QLabel#lblleft color — palette alone is ignored; use inline color.
        self.lblleft.setStyleSheet(
            f'QLabel#lblleft {{ color: {hex_color}; background: transparent; border: none; }}'
        )
        self.lblleft.setAutoFillBackground(False)
        self.lblleft.setText(elided)

    def log(self, text, color='white'):
        """
        Print log info at left label (elided if long). Full text is kept in log history
        and shown in the Logs window (right-click the status line).
        """
        plain = str(text or '')
        self._status_strip_plain = plain
        self._status_strip_color = color
        tip = plain if plain else 'Right-click for log history'
        self.lblleft.setToolTip(tip)
        if plain:
            self._append_log_history(plain, color)
        self._apply_status_strip_elide()
        QTimer.singleShot(0, self._apply_status_strip_elide)

    def _append_log_history(self, text: str, color: str) -> None:
        from datetime import datetime

        entry = LogEntry(ts=datetime.now(), text=text, color=str(color or 'white'))
        self._log_history.append(entry)
        overflow = len(self._log_history) - int(getattr(self, '_log_history_max', 500))
        if overflow > 0:
            del self._log_history[:overflow]
        self._notify_logs_window()

    def log_entries(self):
        """Return a copy of status log history (newest at end)."""
        return list(getattr(self, '_log_history', []) or [])

    def clear_log_history(self) -> None:
        self._log_history = []
        self._notify_logs_window()

    def _notify_logs_window(self) -> None:
        w = getattr(self, 'logs_window', None)
        if w is None or not w.isVisible():
            return
        try:
            w.sync_entries(self.log_entries())
        except Exception:
            pass

    def openLogs(self):
        """Open the advanced log viewer, or focus it if already open."""
        w = self.logs_window
        w.sync_entries(self.log_entries())
        if w.isVisible() and not w.isMinimized():
            w.raise_()
            w.activateWindow()
            return
        if w.isMinimized():
            w.showNormal()
        else:
            w.show()
            w.setWindowState(Qt.WindowNoState)
        w.raise_()
        w.activateWindow()

    def _on_status_log_context_menu(self, pos):
        menu = QMenu(self)
        theme_popup_menu(menu)
        act_open = QAction('Open Logs…', self)
        act_open.triggered.connect(self.openLogs)
        menu.addAction(act_open)
        plain = str(getattr(self, '_status_strip_plain', None) or '').strip()
        if plain:
            act_copy = QAction('Copy message', self)

            def _copy_current():
                try:
                    copy(plain)
                except Exception:
                    QApplication.clipboard().setText(plain)

            act_copy.triggered.connect(_copy_current)
            menu.addAction(act_copy)
        menu.exec_(self.lblleft.mapToGlobal(pos))

    def openSettings(self):
        """Open Settings, or focus it if already open (avoid reload/freeze on re-click)."""
        w = self.settings_window
        already_open = w.isVisible() and not w.isMinimized()
        if already_open:
            w.raise_()
            w.activateWindow()
            return
        if w.isMinimized():
            w.showNormal()
        else:
            w.show()
            w.setWindowState(Qt.WindowNoState)
        w.raise_()
        w.activateWindow()
        # Paint first; avoid ipconfig / settings merge on the click stack.
        QTimer.singleShot(0, w.currentSettings)
        QTimer.singleShot(0, w._load_interfaces_background)

    def openAbout(self):
        """
        Open about window
        """
        w = self.about_window
        if w.isVisible() and not w.isMinimized():
            w.raise_()
            w.activateWindow()
            return
        w.show()
        w.raise_()
        w.activateWindow()

    def openKillFlows(self):
        """Live Kill monitor for the selected victim (in/out rates + cut vs not-in-path)."""
        device = self._get_selected_device()
        if not device or device.get('admin'):
            self.log('Select a client device (not Me/Router).', UI_LOG_RESTORE_FG)
            return
        try:
            self.kill_flows_window.open_for_device(device)
        except Exception as exc:
            self.log(f'Kill Flows failed to open: {exc}', 'red')

    # Back-compat name used by older tray wiring / docs.
    def openTraffic(self):
        self.openKillFlows()

    def table_context_menu(self, pos):
        menu = QMenu(self)
        theme_popup_menu(menu)
        act_traffic = QAction('Kill Flows for Selected', self)
        act_probe = QAction('Manual IP Search…', self)
        act_traffic.triggered.connect(self.openKillFlows)
        act_probe.triggered.connect(self.probe_ip)
        menu.addAction(act_traffic)
        menu.addAction(act_probe)
        menu.addSeparator()
        self._append_scan_column_visibility_actions(menu)
        menu.exec_(self.tableScan.viewport().mapToGlobal(pos))

    def _scan_table_header_context_menu(self, pos):
        menu = QMenu(self)
        theme_popup_menu(menu)
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
        ip, ok = QInputDialog.getText(
            self, 'Manual IP Search', 'Enter IP address to search for:'
        )
        if not ok or not ip:
            return
        self.log(f'Searching for {ip}...', 'aqua')
        hit = self.scanner.probe_ip(ip)
        if hit:
            self.log(f'Discovered {hit[0]} {hit[1]}', UI_LOG_RESTORE_FG)
            self.showDevices()
        else:
            self.log(
                'No response — no MAC in ARP for that IP yet (wrong interface, offline host, '
                'or need Admin/Npcap for a direct search). Try a normal scan or pick the LAN adapter in Settings.',
                'red',
            )

    def applySettings(self):
        """
        Apply saved settings
        """
        self.settings_window.apply_app_settings()

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
        self.logs_window.hide()

    def _ensure_clean_network_on_startup(self) -> None:
        """Remove leftover Kill/Dupe/Lag blocks from a prior session before the user acts."""
        from tools.clumsy_ics import (
            clear_stale_softap_when_tethering_off,
            purge_clumsy_stale_attack_blocks,
        )
        from tools.pfctl import list_blocked_ips
        from tools.windows_network_tune import ensure_home_lan_mitm_forwarding_off

        purge_clumsy_stale_attack_blocks()
        try:
            clear_stale_softap_when_tethering_off()
        except Exception:
            pass
        ensure_home_lan_mitm_forwarding_off()
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
        self._shutting_down = True
        self._teardown_all_attacks(log=True)
        self.settings_window.close()
        self.about_window.close()
        self.logs_window.close()
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
        self.pgbar.valueChanged.connect(self.taskbar_progress.setValue, Qt.QueuedConnection)

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
        self._shutting_down = True
        self._teardown_all_attacks(log=False)
        self.settings_window.close()
        self.about_window.close()
        self.logs_window.close()

        self.hide()
        hide_all_system_tray_icons()

        event.accept()

    def _app_window_title(self) -> str:
        if getattr(self, '_admin_elevated', False):
            return f'{APP_DISPLAY_NAME} — Administrator'
        return APP_DISPLAY_NAME

    def current_index(self):
        return self._get_selected_device()

    def _scan_table_focus_column(self, preferred=0):
        n = self.tableScan.columnCount()
        if 0 <= preferred < n and not self.tableScan.isColumnHidden(preferred):
            return preferred
        for c in range(n):
            if not self.tableScan.isColumnHidden(c):
                return c
        return 0

    def _select_scan_table_row(self, row: int) -> None:
        if row < 0 or row >= self.tableScan.rowCount():
            return
        col = self._scan_table_focus_column()
        self.tableScan.selectRow(row)
        self.tableScan.setCurrentCell(row, col)

    def cellClicked(self, row, column):
        """
        Copy selected cell data to clipboard
        """
        devices = getattr(self.scanner, 'devices', None) or []
        row = resolve_scan_table_click_row(len(devices), row, self.tableScan.currentRow())
        if row < 0:
            return
        device = devices[row]
        if not device.get('admin'):
            self._select_scan_table_row(row)

        keys_order = ['ip', 'mac', 'vendor', 'type', 'name']
        if column < 0 or column >= len(keys_order):
            return
        cell = str(device.get(keys_order[column], ''))

        if len(cell) > 20:
            cell = cell[:20] + '...'
        
        self.lblcenter.setText(cell)
        copy(cell)

    def deviceClicked(self, item=None):
        """
        Disable per-device controls when an admin row is selected.

        itemClicked passes the clicked cell. Prefer that row over currentRow —
        Me/Router can keep currentIndex after a User click on Qt 5.15.
        """
        clicked_row = -1
        if item is not None:
            try:
                clicked_row = int(item.row())
            except Exception:
                clicked_row = -1
        devices = getattr(self.scanner, 'devices', None) or []
        row = resolve_scan_table_click_row(
            len(devices), clicked_row, self.tableScan.currentRow()
        )
        device = devices[row] if row >= 0 else None
        if not device:
            return
        if not device.get('admin'):
            self._select_scan_table_row(row)
        not_enabled = not device.get('admin')
        self._refresh_selected_device_impairment_plan()
        self._reconcile_idle_mitm_state(quiet=True)
        if not_enabled:
            self._schedule_impairment_stack_warm('select')
            self._schedule_npcap_prewarm('select')
            # First click of this IP since last scan only — never on Kill, never every re-click.
            try:
                self._schedule_device_readiness_check(device)
            except Exception:
                pass

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

    def deviceDoubleClicked(self, item=None):
        """
        Open device info window (when not admin)
        """
        clicked_row = -1
        if item is not None:
            try:
                clicked_row = int(item.row())
            except Exception:
                clicked_row = -1
        devices = getattr(self.scanner, 'devices', None) or []
        row = resolve_scan_table_click_row(
            len(devices), clicked_row, self.tableScan.currentRow()
        )
        device = devices[row] if row >= 0 else None
        if not device or device.get('admin'):
            self.log('Admin device', color=UI_LOG_RESTORE_FG)
            return
        
        self.device_window.load(device, row)
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
        # selectable is ignored: Me/Router must stay selectable so Qt can
        # move currentIndex onto a User/PS5 row after a sage-row click.
        _ = selectable
        ql.setFlags(scan_table_item_flags())

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

    def _repaint_device_table_rows(self, device=None) -> None:
        """Repaint only the victim row(s) — avoids scanning every row on flow toggle."""
        if not isinstance(device, dict):
            self._repaint_all_table_rows_for_hover()
            return
        mac = str(device.get('mac') or '').strip()
        if not mac:
            return
        for r, row_dev in enumerate(self.scanner.devices):
            if str(row_dev.get('mac') or '').strip() == mac:
                self._repaint_table_row_for_hover(r)

    def _flush_gui_events(self) -> None:
        try:
            app = QApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.ExcludeUserInputEvents)
        except Exception:
            pass

    def _on_table_selection_for_row_hover(self, *_args):
        self._refresh_selected_device_impairment_plan()
        self._repaint_all_table_rows_for_hover()
        # Keyboard / selection-model paths may not fire itemClicked — still once per IP/scan.
        try:
            device = self._get_selected_device()
            if device and not device.get('admin'):
                self._schedule_device_readiness_check(device)
        except Exception:
            pass

    def fillTableRow(self, row, device):
        texts = [
            str(device.get('ip', '')),
            str(device.get('mac', '')),
            str(device.get('vendor', '')),
            str(device.get('type', '')),
            str(device.get('name', '')),
        ]
        for column, text in enumerate(texts):
            if device.get('admin'):
                admin_colors = [ADMIN_DEVICE_TABLE_ROW_BG, ADMIN_DEVICE_TABLE_ROW_FG]
                self.fillTableCell(row, column, text, admin_colors)
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
        try:
            # Paint path: ARP table only — never scapy getmacbyip (~4s GUI freeze).
            self.scanner.refresh_local_topology(allow_scapy_probe=False)
            self.scanner.add_me()
            self.scanner.add_router()
        except Exception:
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
            sync_clumsy_row(self.scanner, allow_subnet_ping=False)
        except Exception:
            pass
        try:
            self.scanner.inject_nicknamed_favorites()
        except Exception:
            pass
        try:
            from networking.device_table import dedupe_home_lan_rows_by_ip

            self.scanner.devices = dedupe_home_lan_rows_by_ip(
                self.scanner.devices, self.scanner
            )
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
        # Rebuild/restore fires selectionChanged; do not burn the per-scan Ready slot.
        self._readiness_suppress_device_select = True
        try:
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
                self._select_scan_table_row(restore_row)
                self.deviceClicked()
            else:
                self._updateKillButtonState()
                self._updateLagSwitchButtonState()
                self._updateDupeButtonState()
                self.lblcenter.setText('Nothing Selected')
        finally:
            self._readiness_suppress_device_select = False

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
        
        # Re-apply remembered LAN ARP kills. Hotspot Kill is never stored in
        # remembered MACs — restore it from the live Kill profile instead.
        remembered = (get_settings('killed') or []) if self.remember else []
        for rem_device in self.scanner.devices:
            if rem_device.get('admin'):
                continue
            mac = str(rem_device.get('mac') or '').strip()
            if not mac:
                continue
            if mac in remembered and should_restore_remembered_kill(
                rem_device, self.scanner
            ):
                # Cold post-scan ARP/router context — use full arm validation so
                # remembered kills do not silently fail after rescan (fast_arm is
                # for instant UI click paths).
                if not self._apply_victim_block(rem_device, 'both', fast_arm=False):
                    self.log(
                        f"Remembered kill restore failed for "
                        f"{rem_device.get('ip') or mac}.",
                        'red',
                    )
            elif self._is_ics_downstream(rem_device) and self._kill_ui_shows_on(
                mac, rem_device.get('ip'), rem_device
            ):
                # WinDivert path — do not pass fast_arm (not accepted by ICS apply).
                restored = False
                try:
                    gate = getattr(self, '_ics_lag_gate', None)
                    want = str(rem_device.get('ip') or '').strip()
                    if (
                        gate is not None
                        and gate.is_running()
                        and want
                        and str(getattr(gate, 'victim_ip', '') or '').strip() == want
                    ):
                        if hasattr(gate, 'pause_connection'):
                            gate.pause_connection()
                        else:
                            gate.set_blocking(True, mode='pause')
                        restored = bool(gate.is_running())
                    else:
                        restored = bool(self._apply_victim_block(rem_device, 'both'))
                except Exception:
                    restored = False
                if not restored:
                    self.log(
                        f"Hotspot kill restore failed for "
                        f"{rem_device.get('ip') or mac}.",
                        'red',
                    )
                    self._set_killed_profile(rem_device, False)

        # Killer holds ARP for lag/dupe on LAN; explicit Kill uses killed_devices / ICS profiles.
        for mac, victim in self.killer.killed.items():
            if not should_restore_remembered_kill(victim, self.scanner):
                continue
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
            _bg_unblock_ip(_ip)
        
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
        try:
            self._invalidate_device_readiness(reason='post_scan')
        except Exception:
            pass
        self.processDevices()
        try:
            threading.Thread(
                target=safe_daemon_target(lambda: self._schedule_npcap_prewarm('post_scan')),
                name='zubcut-postscan-prewarm',
                daemon=True,
            ).start()
        except Exception:
            pass
        self._schedule_impairment_stack_warm('post_scan')
        try:
            # Refresh once with post-scan router/MAC context (enrich slot).
            self._schedule_pc_readiness_check(reason='post_scan', force=True)
        except Exception:
            pass

    def UpdateThread_Starter(self):
        """
        Periodic HEAD polling refreshes the settings update badge (gear hint).
        Installing builds is only from Settings → Install Latest Build.
        """
        self._start_periodic_update_availability_poll()
        self._start_clumsy_inline_refresh_timer()
        self._start_impairment_warm_on_reactivate()
        self._schedule_impairment_stack_warm('startup')
        try:
            # PC-only readiness in background — never gates Clumsy, never on Kill.
            QTimer.singleShot(800, lambda: self._schedule_pc_readiness_check(reason='startup'))
        except Exception:
            pass

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

    def _schedule_npcap_prewarm(self, reason: str = 'startup') -> None:
        """Background Npcap maintenance + L2 socket warm (no external scripts)."""
        _ = reason
        if getattr(self, '_shutting_down', False):
            return
        iface = ''
        try:
            iface = str(getattr(self.scanner.iface, 'name', None) or '').strip()
        except Exception:
            pass
        from tools.windows_network_tune import schedule_windows_capture_maintenance

        schedule_windows_capture_maintenance(
            iface_name=iface,
            force=reason in ('startup', 'settings', 'post_init'),
            prewarm=self.killer.prewarm_l2_socket,
        )
        # Keep the L2 socket warm while the app is open — cold Npcap opens cost 0.5–2s
        # and make first Kill feel delayed even after a successful startup prewarm.
        if reason != 'keepalive':
            self._ensure_npcap_keepalive_timer()

    def _ensure_npcap_keepalive_timer(self) -> None:
        """Re-prewarm the cached L2 socket every ~90s so instant cut stays hot."""
        if getattr(self, '_npcap_keepalive_timer', None) is not None:
            return
        if getattr(self, '_shutting_down', False):
            return
        try:
            timer = QTimer(self)
            timer.setInterval(90_000)

            def _keepalive() -> None:
                if getattr(self, '_shutting_down', False):
                    return
                try:
                    if not self.killer.l2_socket_ready():
                        self.killer.prewarm_l2_socket(join_ms=0)
                except Exception:
                    pass

            timer.timeout.connect(_keepalive)
            timer.start()
            self._npcap_keepalive_timer = timer
        except Exception:
            self._npcap_keepalive_timer = None

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
        self._update_hint_available = False
        self._update_poll_timer = QTimer(self)
        self._update_poll_timer.setInterval(_UPDATE_POLL_INTERVAL_MS)
        self._update_poll_timer.timeout.connect(self._poll_remote_update_status_foreground)
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state_for_update_poll)
        self._sync_update_poll_timer_for_app_state()
        # Do not require ApplicationActive here — frameless Windows often reports
        # Inactive at startup, which previously skipped the check until focus
        # changed (hours later, even after a full restart).
        QTimer.singleShot(1500, self._poll_remote_update_status_startup)
        QTimer.singleShot(8000, self._poll_remote_update_status_startup)

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

    def _poll_remote_update_status_startup(self):
        self._poll_remote_update_status(require_foreground=False, force_refresh=True)

    def _poll_remote_update_status_foreground(self):
        self._poll_remote_update_status(require_foreground=True)

    def _poll_remote_update_status_daily(self):
        self._poll_remote_update_status(require_foreground=False, force_refresh=True)

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

    def _poll_remote_update_status(self, require_foreground=True, force_refresh=False):
        if not self._should_poll_update_availability():
            return
        if require_foreground and not self._should_run_update_poll_now():
            return
        if self._update_status_poll_thread_is_running():
            return
        # No parent: parenting QThread to the main window has caused lifetime/native issues on Windows.
        poll = _UpdateStatusPollThread(force_refresh=force_refresh)
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
            self._update_hint_available = bool(available)
            sw = getattr(self, 'settings_window', None)
            if sw is not None:
                sw.apply_update_banner_state(available, published_label)
            # Defer gear stylesheet off the signal stack (less re-entrancy with frameless chrome).
            QTimer.singleShot(0, self._sync_settings_gear_update_hint)
        except Exception:
            pass

    def _sync_settings_gear_update_hint(self):
        try:
            sw = getattr(self, 'settings_window', None)
            hinted = bool(getattr(self, '_update_hint_available', False)) or bool(
                getattr(sw, '_update_available', False)
            )
            if hinted:
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
            getattr(self, 'kill_flows_window', None),
            getattr(self, 'logs_window', None),
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

    def _direction_from_checks(self, both_cb, in_cb, out_cb):
        if in_cb.isChecked() and not out_cb.isChecked():
            return 'in'
        if out_cb.isChecked() and not in_cb.isChecked():
            return 'out'
        return 'both'

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

    def _refresh_router_mac_from_system_arp(self) -> None:
        """Populate scanner/killer router MAC from the OS ARP cache (fast ping if missing)."""
        try:
            from tools.utils import (
                good_mac,
                lookup_mac_from_arp_table,
                mac_address_is_usable,
                run_command,
            )

            router_ip = str(
                getattr(self.scanner, 'router_ip', None)
                or (getattr(self.scanner, 'router', None) or {}).get('ip')
                or ''
            ).strip()
            if not router_ip:
                return
            iface_ip = str(getattr(self.scanner.iface, 'ip', None) or '').strip()
            mac = lookup_mac_from_arp_table(router_ip, iface_ip)
            if not mac_address_is_usable(mac) and sys.platform.startswith('win'):
                try:
                    run_command(
                        ['ping', '-n', '1', '-w', '500', router_ip],
                        shell=False,
                        timeout=1,
                    )
                except Exception:
                    pass
                mac = lookup_mac_from_arp_table(router_ip, iface_ip)
            if not mac_address_is_usable(mac):
                return
            mine = good_mac(
                getattr(getattr(self.scanner, 'iface', None), 'mac', None) or ''
            )
            if mine and good_mac(mac) == mine:
                return
            self.scanner.router_mac = mac
            if isinstance(getattr(self.scanner, 'router', None), dict):
                self.scanner.router['mac'] = mac
            if isinstance(getattr(self.killer, 'router', None), dict):
                self.killer.router['mac'] = mac
        except Exception:
            pass

    def _reconcile_network_adapter(self, *, log: bool = True) -> None:
        """Keep Me/Router rows aligned with the Settings network adapter."""
        try:
            from tools.utils import reconcile_scanner_with_settings_iface

            hint = reconcile_scanner_with_settings_iface(self.scanner, self.killer)
            if not hint:
                return
            self.showDevices()
            if log:
                self.log(f'Network adapter synced: {hint}', UI_LOG_RESTORE_FG)
        except Exception:
            pass

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

    def _ignore_duplicate_toggle_edge(self, kind: str, mac: str | None, edge: str) -> bool:
        """
        Ignore a second identical edge (same MAC, same activate/stop/…) within a few
        ms — filters duplicate clicks / key deliveries. Alternating on/off is not delayed.
        Held keys: use QShortcut.setAutoRepeat(False).
        """
        ctrl = getattr(self, '_impairment', None)
        if ctrl is not None:
            return ctrl.ignore_duplicate_toggle_edge(kind, mac, edge)
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

    @staticmethod
    def _toggle_kind_label(kind):
        return _impairment_toggle_kind_label(kind)

    def _active_toggle_kind(self):
        ctrl = getattr(self, '_impairment', None)
        if ctrl is not None:
            return ctrl.active_toggle_kind()
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

    def _get_selected_device(self):
        """Current table row device (toolbar clicks clear selection; currentRow still identifies victim)."""
        devices = getattr(self.scanner, 'devices', None) or []
        row = self.tableScan.currentRow()
        if 0 <= row < len(devices):
            return devices[row]
        for ix in self.tableScan.selectedIndexes():
            r = ix.row()
            if 0 <= r < len(devices):
                return devices[r]
        return None

    def _get_device_by_mac(self, mac, ip=None):
        matches = [d for d in self.scanner.devices if d.get('mac') == mac]
        if not matches:
            return None
        want_ip = (ip or '').strip()
        if want_ip:
            for device in matches:
      