import time

from pyperclip import copy

from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QMessageBox, \
                            QMenu, QSystemTrayIcon, QAction, QPushButton, \
                            QDialog, QFormLayout, QDialogButtonBox, QSpinBox, \
                            QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QGroupBox, \
                            QSizePolicy, QShortcut, QAbstractSpinBox, QLineEdit, \
                            QTextEdit, QPlainTextEdit, QWidget
from PyQt5.QtGui import QPixmap, QIcon, QFont, QKeySequence
from PyQt5.QtCore import Qt, QTimer, QSize, QElapsedTimer
try:
    from PyQt5.QtWinExtras import QWinTaskbarButton
except Exception:
    QWinTaskbarButton = None

from ui.ui_main import Ui_MainWindow

from gui.settings import Settings
from gui.about import About
from gui.device import Device
from gui.traffic import Traffic

from networking.scanner import Scanner
from networking.killer import Killer

from tools.qtools import colored_item, MsgType, Buttons, clickable
from tools.utils_gui import (
    set_settings,
    get_settings,
    import_settings,
    zubcut_dark_stylesheet,
    sync_translucent_chrome,
    register_window_surface_effects,
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
from tools.utils import goto, is_connected, get_default_iface
from tools.pfctl import block_ip, unblock_ip

from assets import *

from bridge import ScanThread  # UpdateThread disabled for fork

from constants import *

# from qt_material import build_stylesheet


def _focus_widget_absorbs_letter_key(widget):
    """Avoid stealing L while typing in numeric/text fields."""
    if widget is None:
        return False
    return isinstance(widget, (QAbstractSpinBox, QLineEdit, QTextEdit, QPlainTextEdit))


class LagSwitchDialog(FramelessResizableMixin, QDialog):
    """Non-modal panel: edit lag / allow times, then toggle lag switch on or off."""

    def __init__(self, parent=None):
        super().__init__(parent)
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
        root.addWidget(CustomTitleBar(self, 'Lag Switch', lag_icon, maximizable=False))

        body = QWidget(self)
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

        btn_heavy = QPushButton('Heavy (3000/1000)')
        btn_heavy.clicked.connect(lambda: self._set_preset(3000, 1000))
        self._preset_buttons.append(btn_heavy)
        preset_layout.addWidget(btn_heavy)

        layout.addLayout(preset_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, body)
        buttons.rejected.connect(self.hide)
        layout.addWidget(buttons)

        root.addWidget(body, 1)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
        register_window_surface_effects(self)

    def _on_m_key_pressed(self):
        if QApplication.activeWindow() is not self:
            return
        if not self.isActiveWindow():
            return
        if _focus_widget_absorbs_letter_key(self.focusWidget()):
            return
        # Same path as btnLagStartStop.clicked
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

        deb_mac = None
        if main.tableScan.selectedItems():
            try:
                deb_mac = main.current_index()['mac']
            except Exception:
                pass
        lag_edge = 'start'
        if main._ignore_duplicate_toggle_edge('lag', deb_mac, lag_edge):
            return
        if not main.tableScan.selectedItems():
            main.log('No device selected', 'red')
            return
        device = main.current_index()
        if device['admin']:
            main.log('Cannot lag admin device', 'orange')
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
        root.addWidget(CustomTitleBar(self, 'Dupe', dupe_icon, maximizable=False))

        body = QWidget(self)
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
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
        register_window_surface_effects(self)

    def _on_p_key_pressed(self):
        if QApplication.activeWindow() is not self:
            return
        if not self.isActiveWindow():
            return
        if _focus_widget_absorbs_letter_key(self.focusWidget()):
            return
        # Same path as btnDupeRun.clicked
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
        if left_ms is None:
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

        deb_mac = None
        if main.tableScan.selectedItems():
            try:
                deb_mac = main.current_index()['mac']
            except Exception:
                pass
        dupe_edge = 'start'
        if main._ignore_duplicate_toggle_edge('dupe', deb_mac, dupe_edge):
            return
        if not main.tableScan.selectedItems():
            main.log('No device selected', 'red')
            return
        device = main.current_index()
        if device['admin']:
            main.log('Cannot dupe admin device', 'orange')
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
        self.setStyleSheet(zubcut_dark_stylesheet())
        # Rebalance top toolbar row so right-side empty space is used more evenly.
        self.gridLayout.removeWidget(self.btnSettings)
        self.gridLayout.removeWidget(self.btnAbout)
        self.gridLayout.addWidget(self.btnSettings, 0, 6, 2, 1)
        self.gridLayout.addWidget(self.btnAbout, 0, 7, 2, 2)
        self.gridLayout.setColumnStretch(0, 0)
        for _col in range(1, 9):
            self.gridLayout.setColumnStretch(_col, 1)

        # Space was bound in the .ui to ARP scan; only fire when the main window is foreground.
        self.btnScanEasy.setShortcut(QKeySequence())
        sc_arp_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc_arp_space.setContext(Qt.WindowShortcut)
        sc_arp_space.setAutoRepeat(False)
        sc_arp_space.activated.connect(self._shortcut_scan_easy)

        self._shortcut_kill_l = QShortcut(QKeySequence(Qt.Key_L), self)
        self._shortcut_kill_l.setContext(Qt.WindowShortcut)
        self._shortcut_kill_l.setAutoRepeat(False)
        self._shortcut_kill_l.activated.connect(self._shortcut_main_l)

        # Main Props
        self.scanner = Scanner()
        self.killer = Killer()
        self.killed_devices = {}  # MAC -> bool kill toggle state
        self.lag_active = False
        self.lag_block_ms = 1500
        self.lag_release_ms = 1500
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
        self.BUTTON_NORMAL_STYLE = ""

        # Settings props
        self.minimize = True
        self.remember = False
        self.autoupdate = False  # Disabled - this is a fork

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
            (self.btnKillAll,    self.killAll,       killall_icon,    'Kill All - Block internet access for ALL devices on the network'),
            (self.btnUnkillAll,  self.unkillAll,     unkillall_icon,  'Unkill All - Restore internet access for all blocked devices'),
            (self.btnSettings,   self.openSettings,  settings_icon,   'Settings - Configure scan options and network interface'),
            (self.btnAbout,      self.openAbout,     None,            f'About {APP_DISPLAY_NAME} - View credits and version info')
        ] 
        
        for btn, btn_func, btn_icon, btn_tip in self.buttons:
            btn.setToolTip(btn_tip)
            btn.clicked.connect(btn_func)
            if btn_icon is not None:
                btn.setIcon(self.processIcon(btn_icon))
        self.btnAbout.setIcon(self.icon)
        self.btnAbout.setIconSize(QSize(48, 48))

        self.btnKill = QPushButton(self.centralwidget)
        self.btnKill.setObjectName('btnKill')
        self.btnKill.setMinimumHeight(88)
        self.btnKill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btnKill.setToolTip(
            'Kill toggle — Turn blocking on or off for the selected device. '
            'Shortcut: L (only while the main ZubCut window is the active window).'
        )
        self.btnKill.setIcon(self.processIcon(kill_icon))
        self.btnKill.setMinimumWidth(130)
        self.btnKill.setIconSize(QSize(56, 56))
        kill_font = QFont(self.btnKill.font())
        kill_font.setPointSize(13)
        kill_font.setBold(True)
        self.btnKill.setFont(kill_font)
        # Use pressed instead of clicked so fast double-clicks count as two toggles.
        self.btnKill.pressed.connect(self.toggleKill)

        self.btnLagSwitch = QPushButton('Lag Switch', self)
        self.btnLagSwitch.setMinimumHeight(88)
        self.btnLagSwitch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btnLagSwitch.setToolTip(
            'Lag Switch — Opens a window where you set lag / allow times and toggle intermittent blocking on or off. '
            'Shortcut: M starts/stops while the Lag Switch window is active (L is Kill on the main window).'
        )
        self.gridLayout.addWidget(self.btnLagSwitch, 5, 1, 1, 3)
        self.btnLagSwitch.clicked.connect(self.openLagSwitchDialog)
        lag_font = QFont(self.btnLagSwitch.font())
        lag_font.setPointSize(14)
        lag_font.setBold(True)
        self.btnLagSwitch.setFont(lag_font)

        self.gridLayout.addWidget(self.btnKill, 5, 4, 1, 2)

        self.btnDupe = QPushButton('Dupe', self)
        self.btnDupe.setMinimumHeight(88)
        self.btnDupe.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        dupe_font = QFont(self.btnDupe.font())
        dupe_font.setPointSize(14)
        dupe_font.setBold(True)
        self.btnDupe.setFont(dupe_font)
        self.btnDupe.setToolTip(
            'Dupe — One-shot lag for a set time (ms), then full stop. '
            'Does not repeat; use Lag Switch for cycles. '
            'Shortcut: P runs/stops while the Dupe window is active.'
        )
        self.gridLayout.addWidget(self.btnDupe, 5, 6, 1, 3)
        self.btnDupe.clicked.connect(self.openDupeDialog)

        self.lag_switch_dialog = None
        self.dupe_switch_dialog = None

        self.refresh_keyboard_shortcuts_from_settings()

        self.lblDonate.setText('ZubCut')
        
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

        '''
           System tray icon and it's tray menu
        '''
        show_option = QAction('Show', self)
        hide_option = QAction('Hide', self)
        quit_option = QAction('Quit', self)
        kill_option = QAction(self.processIcon(kill_icon), '&Kill All', self)
        unkill_option = QAction(self.processIcon(unkillall_icon), '&Unkill All', self)
        
        show_option.triggered.connect(self.trayShowClicked)
        hide_option.triggered.connect(self.hide_all)
        quit_option.triggered.connect(self.quit_all)
        kill_option.triggered.connect(self.killAll)
        unkill_option.triggered.connect(self.unkillAll)
        
        tray_menu = QMenu()
        tray_menu.addAction(show_option)
        tray_menu.addAction(hide_option)
        tray_menu.addSeparator()
        tray_menu.addAction(kill_option)
        tray_menu.addAction(unkill_option)
        tray_menu.addSeparator()
        self.traffic_option = QAction('Traffic for Selected', self)
        self.traffic_option.triggered.connect(self.openTraffic)
        tray_menu.addAction(self.traffic_option)
        tray_menu.addAction(quit_option)
        
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.icon)
        self.tray_icon.setToolTip(APP_DISPLAY_NAME)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self.tray_clicked)

        # Taskbar button (Windows only)
        self.taskbar_button = None
        self.taskbar_progress = None

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

    def log(self, text, color='white'):
        """
        Print log info at left label
        """
        self.lblleft.setText(f"<font color='{color}'>{text}</font>")
    
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
            self.log('Admin device', 'orange')
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
        menu.exec_(self.tableScan.viewport().mapToGlobal(pos))

    def probe_ip(self):
        from PyQt5.QtWidgets import QInputDialog
        ip, ok = QInputDialog.getText(self, 'Probe IP', 'Enter IP to probe:')
        if not ok or not ip:
            return
        self.log(f'Probing {ip}...', 'aqua')
        hit = self.scanner.probe_ip(ip)
        if hit:
            self.log(f'Discovered {hit[0]} {hit[1]}', 'lime')
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
        self.killer.unkill_all()
        self.stopLagSwitch()
        self.stopDupe(log=False)
        self.settings_window.close()
        self.about_window.close()
        self.tray_icon.hide()
        self.from_tray = True
        self.close()

    def showEvent(self, event):
        """
        https://stackoverflow.com/a/60123914/5305953
        Connect TaskBar icon to progressbar
        """
        if QWinTaskbarButton is None:
            return
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

    def closeEvent(self, event):
        """
        Run in background if self.minimize is True else exit
        """
        self.stopLagSwitch()
        self.stopDupe(log=False)
        # If event recieved from tray icon
        if self.from_tray:
            event.accept()
            return
        
        # If event is recieved from close X button

        ## If minimize is true
        if self.minimize:
            event.ignore()
            self.hide_all()
            return

        ## If not, ukill all and shutdown
        self.killer.unkill_all()
        self._sync_killed_devices()
        self.settings_window.close()
        self.about_window.close()

        self.hide()
        self.tray_icon.hide()

        QMessageBox.information(
            self,
            'Shutdown',
            f'{APP_DISPLAY_NAME} will exit completely.\n\n'
            'Enable minimized from settings\n'
            'to be able to run in background.'
        )

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
        
        self._updateKillButtonState()
        self._updateLagSwitchButtonState()
        self._updateDupeButtonState()
        if getattr(self, 'lag_switch_dialog', None) and self.lag_switch_dialog.isVisible():
            self.lag_switch_dialog.refresh_toggle_state()
        if getattr(self, 'dupe_switch_dialog', None) and self.dupe_switch_dialog.isVisible():
            self.dupe_switch_dialog.refresh_toggle_state()

    def _updateLagSwitchButtonState(self):
        """Update lag switch button based on whether it's active for selected device."""
        if self.lag_active and self.lag_device_mac:
            self.btnLagSwitch.setText('■ LAGGING')
            self.btnLagSwitch.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnLagSwitch.setText('Lag Switch')
            self.btnLagSwitch.setStyleSheet(self.BUTTON_NORMAL_STYLE)
    
    def deviceDoubleClicked(self):
        """
        Open device info window (when not admin)
        """
        device = self.current_index()
        if device['admin']:
            self.log('Admin device', color='orange')
            return
        
        self.device_window.load(device, self.tableScan.currentRow())
        self.device_window.hide()
        self.device_window.show()
        self.device_window.setWindowState(Qt.WindowNoState)
    
    def fillTableCell(self, row, column, text, colors=[]):
        # Center text in table cell
        ql = QTableWidgetItem()
        ql.setText(text)
        ql.setTextAlignment(Qt.AlignCenter)

        if colors:
            colored_item(ql, *colors)
        
        # Add cell to the specific location
        self.tableScan.setItem(row, column, ql)

    def fillTableRow(self, row, device):
        for column, text in enumerate(device.values()):
            # Skip 'admin' key
            if type(text) == bool:
                continue
            
            # Highlight Admins in green
            if device['admin']:
                self.fillTableCell(
                    row,
                    column,
                    text,
                    ['#00ff00', '#000000']
                )
            else:
                self.fillTableCell(
                    row,
                    column,
                    text,
                    # Highlight killed devices in red else transparent
                    ['#ff0000', '#ffffff'] * (device['mac'] in self.killer.killed)
                )

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
        self.tableScan.clearSelection()
        self.tableScan.clearContents()
        self.tableScan.setRowCount(len(self.scanner.devices))

        for row, device in enumerate(self.scanner.devices):
            self.fillTableRow(row, device)
        
        status = f'{len(self.scanner.devices) - 2} devices' \
                 f' ({len(self.killer.killed)} killed)'
        
        status_tray = f'Devices Found: {len(self.scanner.devices) - 2}\n' \
                      f'Devices Killed: {len(self.killer.killed)}\n' \
                      f'Interface: {self.scanner.iface.name}'
        
        self.lblright.setText(status)
        self.tray_icon.setToolTip(status_tray)

        # Restore selection when possible so toggle states stay in sync
        if 0 <= current_row < len(self.scanner.devices):
            self.tableScan.selectRow(current_row)
            self.tableScan.setCurrentCell(current_row, 0)
            self.deviceClicked()
        else:
            self._updateKillButtonState()
            self._updateLagSwitchButtonState()
            self._updateDupeButtonState()
            self.lblcenter.setText('Nothing Selected')
    
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
            'orange'
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
        self.killer.kill(device)
        self.killed_devices[device['mac']] = True
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
        self.log('Killed ' + device['ip'], 'fuchsia')
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
        self.killer.unkill(victim)
        self.killed_devices[device['mac']] = False
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
        self.log('Unkilled ' + device['ip'], 'lime')

        self._updateKillButtonState()
        self.showDevices()
    
    # @check_connection
    def killAll(self):
        """
        Kill all scanned devices except admins
        """
        self.stopLagSwitch()
        self.stopDupe(log=False)
        if not self.connected():
            return
        
        self.killer.kill_all(self.scanner.devices)
        for mac in self.killer.killed:
            self.killed_devices[mac] = True
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
        self.log('Killed All devices', 'fuchsia')

        self.showDevices()

    # @check_connection
    def unkillAll(self):
        """
        Unkill all killed devices except admins.
        Clears lag switches and dupe bursts.
        """
        self.stopLagSwitch()
        self.stopDupe(log=False)
        if not self.connected():
            return
        
        self.killer.unkill_all()
        self.killed_devices.clear()
        self._sync_killed_devices()
        set_settings('killed', list(self.killer.killed) * self.remember)
        self.log('Unkilled All devices', 'lime')

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
        if not self.connected(show_msg_box=True):
            return

        self.centralwidget.setEnabled(False)
        
        # Save copy of killed devices
        self.killer.store()
        
        self.killer.unkill_all()
        
        self.log(
            ['Arping', 'Pinging'][scan_type] + ' your network...',
            ['aqua', 'fuchsia'][scan_type]
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
        Update Thread starter - Disabled for fork
        """
        pass  # Update checking disabled for this fork

    def UpdateThread_Reciever(self):
        """
        Update Thread reciever - Disabled for fork
        """
        pass  # Update checking disabled for this fork
    
    def _main_window_is_foreground(self):
        aw = QApplication.activeWindow()
        return aw is not None and aw is self

    def _shortcut_scan_easy(self):
        if not self._main_window_is_foreground():
            return
        if self.btnScanEasy.isEnabled():
            self.scanEasy()

    def refresh_keyboard_shortcuts_from_settings(self):
        """Apply key_kill / key_lag / key_dupe from settings to shortcuts and tooltips."""
        s = import_settings()
        k_kill = keyseq_from_setting(s.get('key_kill'), Qt.Key_L)
        k_lag = keyseq_from_setting(s.get('key_lag'), Qt.Key_M)
        k_dupe = keyseq_from_setting(s.get('key_dupe'), Qt.Key_P)
        self._shortcut_kill_l.setKey(k_kill)
        self._shortcut_kill_l.setAutoRepeat(False)
        nk = k_kill.toString(QKeySequence.NativeText)
        nl = k_lag.toString(QKeySequence.NativeText)
        np = k_dupe.toString(QKeySequence.NativeText)
        self._btn_kill_tooltip_static = (
            'Kill toggle — Turn blocking on or off for the selected device. '
            'Shortcut: %s (only while the main ZubCut window is the active window).' % nk
        )
        self.btnKill.setToolTip(self._btn_kill_tooltip_static)
        self.btnLagSwitch.setToolTip(
            'Lag Switch — Opens a window where you set lag / allow times and toggle intermittent blocking on or off. '
            'Shortcut: %s starts/stops while the Lag Switch window is active (%s is Kill on the main window).'
            % (nl, nk)
        )
        self.btnDupe.setToolTip(
            'Dupe — One-shot lag for a set time (ms), then full stop. '
            'Does not repeat; use Lag Switch for cycles. '
            'Shortcut: %s runs/stops while the Dupe window is active.' % np
        )
        lag = self.lag_switch_dialog
        if lag:
            lag._shortcut_m.setKey(k_lag)
            lag._shortcut_m.setAutoRepeat(False)
            lag.btnLagStartStop.setToolTip(
                'Start or stop intermittent lag for the device selected in the main list. '
                'Shortcut: %s when this window is active (not in ms fields).' % nl
            )
        dupe = self.dupe_switch_dialog
        if dupe:
            dupe._shortcut_p.setKey(k_dupe)
            dupe._shortcut_p.setAutoRepeat(False)
            dupe.btnDupeRun.setToolTip(
                'Run a single lag burst for the device selected in the main list, then stop completely. '
                'Shortcut: %s when this window is active (not in ms fields).' % np
            )

    def _shortcut_main_l(self):
        """Kill toggle when the main window is active (focused), using the configured shortcut."""
        if QApplication.activeWindow() is not self:
            return
        if not self.isActiveWindow():
            return
        if _focus_widget_absorbs_letter_key(self.focusWidget()):
            return
        # Same handler as btnKill.clicked — do not gate on btnKill.isEnabled(); toggleKill
        # enforces connected(), selection, and admin the same for mouse and keyboard.
        self.toggleKill()

    def openLagSwitchDialog(self):
        if not self.connected():
            return
        if not self.tableScan.selectedItems():
            self.log('No device selected', 'red')
            return
        device = self.current_index()
        if device['admin']:
            self.log('Cannot lag admin device', 'orange')
            return
        if self.lag_switch_dialog is None:
            self.lag_switch_dialog = LagSwitchDialog(self)
            self.refresh_keyboard_shortcuts_from_settings()
        self.lag_switch_dialog.show()
        self.lag_switch_dialog.raise_()
        self.lag_switch_dialog.activateWindow()

    def openDupeDialog(self):
        if not self.connected():
            return
        if not self.tableScan.selectedItems():
            self.log('No device selected', 'red')
            return
        device = self.current_index()
        if device['admin']:
            self.log('Cannot dupe admin device', 'orange')
            return
        if self.dupe_switch_dialog is None:
            self.dupe_switch_dialog = DupeDialog(self)
            self.refresh_keyboard_shortcuts_from_settings()
        self.dupe_switch_dialog.show()
        self.dupe_switch_dialog.raise_()
        self.dupe_switch_dialog.activateWindow()

    def applyLagSwitchSettings(self, block_ms, release_ms, direction):
        self.lag_block_ms = block_ms
        self.lag_release_ms = release_ms
        self.lag_direction = direction

    def _refresh_lag_timing_from_dialog(self):
        """Keep lag_block_ms / lag_release_ms in sync with the panel (each phase and while editing)."""
        d = getattr(self, 'lag_switch_dialog', None)
        if d is None or not d.isVisible():
            return
        try:
            lag_ms, normal_ms, direction = d.values()
            self.applyLagSwitchSettings(lag_ms, normal_ms, direction)
        except Exception:
            pass

    def startLagSwitch(self, device):
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
            'orange',
        )
        self._lag_apply_block(device)
        self._lag_in_allow_phase = False
        self.lag_timer.start(max(1, int(self.lag_block_ms)))
        if self.lag_switch_dialog and self.lag_switch_dialog.isVisible():
            self.lag_switch_dialog.refresh_toggle_state()
        self._updateKillButtonState()

    def _refresh_table_row_for_mac(self, mac):
        """Update table row colors for one MAC without rebuilding the whole table."""
        if not mac:
            return
        for row, d in enumerate(self.scanner.devices):
            if d['mac'] == mac:
                self.fillTableRow(row, d)
                break

    def _apply_victim_block(self, device, direction):
        if device['mac'] not in self.killer.killed:
            self.killer.kill(device)
        iface = self.scanner.iface.name if self.scanner.iface else 'en0'
        block_ip(iface, device['ip'], direction)
        self._sync_killed_devices()
        self._refresh_table_row_for_mac(device['mac'])
        self._updateKillButtonState()

    def _clear_victim_block(self, device):
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
            try:
                unblock_ip(device['ip'])
            except Exception:
                pass
            victim = self._victim_record_for_mac(prev_mac) or device
            if victim:
                try:
                    self.killer.unkill(victim)
                    self.killer.reinforce_restore(victim)
                except Exception:
                    pass
        self._sync_killed_devices()
        self.btnLagSwitch.setText('Lag Switch')
        self.btnLagSwitch.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self.log('Lag switch OFF', 'lime')
        if refresh_dialog and self.lag_switch_dialog and self.lag_switch_dialog.isVisible():
            self.lag_switch_dialog.refresh_toggle_state()
        self._updateLagSwitchButtonState()
        self._updateKillButtonState()

    def startDupe(self, device, duration_ms, direction):
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
        self.log(f'Dupe: {duration_ms}ms ({dir_text}), then full stop', 'orange')
        self._dupe_elapsed.start()
        self.dupe_timer.start(max(1, int(duration_ms)))
        self._dupe_countdown_timer.start()
        self._tick_dupe_countdown()
        if getattr(self, 'dupe_switch_dialog', None) and self.dupe_switch_dialog.isVisible():
            self.dupe_switch_dialog.refresh_toggle_state()

    def dupe_remaining_ms(self):
        if not self.dupe_active:
            return None
        return max(0, int(self.dupe_duration_ms - self._dupe_elapsed.elapsed()))

    def _tick_dupe_countdown(self):
        if not self.dupe_active:
            self._dupe_countdown_timer.stop()
            dlg = getattr(self, 'dupe_switch_dialog', None)
            if dlg:
                dlg.set_dupe_countdown(None)
            return
        rem = self.dupe_remaining_ms()
        dlg = getattr(self, 'dupe_switch_dialog', None)
        if dlg and dlg.isVisible():
            dlg.set_dupe_countdown(rem)

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
        dlg = getattr(self, 'dupe_switch_dialog', None)
        if dlg:
            dlg.set_dupe_countdown(None)
        device = self._get_device_by_mac(prev_mac)
        if device:
            try:
                self._clear_victim_block(device)
            except Exception:
                pass
        self.btnDupe.setText('Dupe')
        self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        if log:
            self.log(log_message, 'lime')
        if refresh_dialog and getattr(self, 'dupe_switch_dialog', None) and self.dupe_switch_dialog.isVisible():
            self.dupe_switch_dialog.refresh_toggle_state()
        self._updateDupeButtonState()
        self._updateKillButtonState()

    def _updateDupeButtonState(self):
        if self.dupe_active and self.dupe_device_mac:
            self.btnDupe.setText('■ DUPE')
            self.btnDupe.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnDupe.setText('Dupe')
            self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)

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

    def toggleKill(self):
        if not self.connected():
            return
        device = self._get_selected_device()
        if not device:
            self.log('No device selected', 'red')
            return
        if device['admin']:
            self.log('Cannot kill admin device', 'orange')
            return

        mac = device['mac']
        # Lag/Dupe use killer/MITM for this MAC. A Kill press must mean "stop MITM" for that
        # flow, not flip the Kill toggle ON (avoids desync with double keybind / rapid clicks).
        if self.lag_active and self.lag_device_mac == mac:
            self.stopLagSwitch(refresh_dialog=True)
            self._enqueue_kill_off_only(mac, device)
            return
        if self.dupe_active and self.dupe_device_mac == mac:
            self.stopDupe(refresh_dialog=True, log=False)
            self._enqueue_kill_off_only(mac, device)
            return

        desired_map = getattr(self, '_kill_desired_state', None)
        if desired_map is None:
            desired_map = {}
            self._kill_desired_state = desired_map
        current_target = bool(desired_map.get(mac, mac in self.killer.killed))
        next_state = not current_target
        desired_map[mac] = next_state
        self.log(
            f'[DBG kill click] mac={mac} current_target={int(current_target)} '
            f'next_target={int(next_state)} actual_on={int(mac in self.killer.killed)}',
            'aqua',
        )
        snapshot_map = getattr(self, '_kill_device_snapshot', None)
        if snapshot_map is None:
            snapshot_map = {}
            self._kill_device_snapshot = snapshot_map
        snapshot_map[mac] = dict(device)
        self.killed_devices[mac] = next_state

        self._updateKillButtonState()
        self._schedule_kill_apply()

    def _kill_ui_shows_on(self, mac):
        """Kill button / bookkeeping: ON if desired target is ON; else backend state."""
        desired_map = getattr(self, '_kill_desired_state', None) or {}
        if mac in desired_map:
            return bool(desired_map[mac])
        return mac in self.killer.killed

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
        desired_map = getattr(self, '_kill_desired_state', None) or {}
        for mac in list(self.killed_devices.keys()):
            if mac not in active_macs:
                if mac in desired_map:
                    self.killed_devices[mac] = self._kill_ui_shows_on(mac)
                else:
                    self.killed_devices[mac] = False

    def _updateKillButtonState(self):
        device = self._get_selected_device()
        if not device:
            self.btnKill.setText('Kill: OFF')
            self.btnKill.setStyleSheet(self.BUTTON_NORMAL_STYLE)
            if getattr(self, '_btn_kill_tooltip_static', None):
                self.btnKill.setToolTip(self._btn_kill_tooltip_static)
            return

        mac = device['mac']
        base_tip = getattr(self, '_btn_kill_tooltip_static', None)
        if self.lag_active and self.lag_device_mac == mac:
            self.btnKill.setText('■ LAGGING')
            self.btnKill.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
            if base_tip:
                self.btnKill.setToolTip(
                    base_tip
                    + ' While lag switch is running for this device, this stops lag and restores traffic (it does not turn Kill on).'
                )
            return
        if self.dupe_active and self.dupe_device_mac == mac:
            self.btnKill.setText('■ DUPE')
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
            self.btnKill.setText('■ KILL: ON')
            self.btnKill.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
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
        """After lag/dupe stop: force OFF target so kill apply reconciles backend."""
        desired_map = getattr(self, '_kill_desired_state', None)
        if desired_map is None:
            desired_map = {}
            self._kill_desired_state = desired_map
        desired_map[mac] = False
        snapshot_map = getattr(self, '_kill_device_snapshot', None)
        if snapshot_map is None:
            snapshot_map = {}
            self._kill_device_snapshot = snapshot_map
        snapshot_map[mac] = dict(device)
        self.killed_devices[mac] = False
        self._updateKillButtonState()
        self._schedule_kill_apply()

    def _schedule_kill_apply(self):
        if getattr(self, '_kill_apply_scheduled', False):
            return
        self._kill_apply_scheduled = True
        QTimer.singleShot(0, self._flush_kill_desired_state)

    def _flush_kill_desired_state(self):
        self._kill_apply_scheduled = False
        if getattr(self, '_kill_apply_running', False):
            self._schedule_kill_apply()
            return
        desired_map = getattr(self, '_kill_desired_state', None) or {}
        pending = [(m, bool(desired_map[m])) for m in list(desired_map.keys())]
        if not pending:
            return
        self._kill_apply_running = True
        try:
            snapshot_map = getattr(self, '_kill_device_snapshot', {})
            for mac, target_on in pending:
                desired_map.pop(mac, None)
                device = self._get_device_by_mac(mac) or snapshot_map.get(mac)
                actual_on = mac in self.killer.killed
                self.log(
                    f'[DBG kill apply] mac={mac} target_on={int(target_on)} '
                    f'actual_on={int(actual_on)} queued_left={len(desired_map)}',
                    'aqua',
                )

                if target_on:
                    if self.lag_active and self.lag_device_mac == mac:
                        self.stopLagSwitch(refresh_dialog=True)
                    if self.dupe_active and self.dupe_device_mac == mac:
                        self.stopDupe(log=False)

                if target_on == actual_on:
                    if not target_on and device:
                        self.killer.reinforce_restore(device)
                        self.log(
                            f'[DBG kill action] mac={mac} action=reinforce_restore_only',
                            'aqua',
                        )
                    else:
                        self.log(
                            f'[DBG kill action] mac={mac} action=noop_state_already_match',
                            'aqua',
                        )
                    self.killed_devices[mac] = self._kill_ui_shows_on(mac)
                    continue

                if target_on:
                    if device:
                        self.killer.kill(device)
                        self.log('Kill ON for ' + device['ip'], 'fuchsia')
                        self.log(f'[DBG kill action] mac={mac} action=kill', 'aqua')
                else:
                    victim = self._victim_record_for_mac(mac) or device
                    if victim:
                        self.killer.unkill(victim)
                        self.killer.reinforce_restore(victim)
                        if actual_on:
                            self.killer.reinforce_restore(victim)
                        self.log('Kill OFF for ' + victim['ip'], 'lime')
                        self.log(f'[DBG kill action] mac={mac} action=unkill_restore', 'aqua')

                self.killed_devices[mac] = self._kill_ui_shows_on(mac)

            self._sync_killed_devices()
            set_settings('killed', list(self.killer.killed) * self.remember)
            self._updateKillButtonState()
            self.showDevices()
        finally:
            self._kill_apply_running = False
            desired_map = getattr(self, '_kill_desired_state', None) or {}
            if desired_map:
                self._schedule_kill_apply()

