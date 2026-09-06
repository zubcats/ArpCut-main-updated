"""Clumzy Mode main window — ZubCut chrome, Clumzy engine only. No ARP / Killer / Npcap cut path."""
from __future__ import annotations

import sys
import time

from PyQt5.QtCore import Qt, QSize, QTimer, QEvent, QObject
from PyQt5.QtGui import QFont, QKeySequence, QIcon, QPixmap, QFontMetrics
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from assets import app_icon, kill_icon, scan_easy_icon, scan_hard_icon, settings_icon
from constants import (
    ADMIN_DEVICE_TABLE_ROW_BG,
    APP_DISPLAY_NAME,
    TABLE_HEADER_LABELS,
    UI_LOG_RESTORE_FG,
    UI_LOG_VICTIM_BLOCK_FG,
    UI_TABLE_SELECTION_BG,
)
from gui.about import About
from gui.advanced_lag_settings import AdvancedLagSettingsDialog
from gui.logs_window import log_color_to_hex
from gui.settings import Settings
from tools.branding import (
    LOGO_UI_CONTENT_FRACTION,
    crop_logo_content,
    load_application_qicon,
    load_shell_window_icon,
    qicon_is_empty,
)
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
    import_settings,
    is_admin,
    set_settings,
    set_settings_many,
    sync_translucent_chrome,
    theme_popup_menu,
)
from ui.ui_main import Ui_MainWindow


def _chrome_pushbutton_hover_inline_qss(_watched_btn=None) -> str:
    return (
        'background-color: #383838; color: #d0d0d0; border: 1px solid #383838; border-radius: 4px;'
    )


class _ChromePushButtonHoverFilter(QObject):
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


class ClumzyModeWindow(FramelessResizableMixin, QMainWindow, Ui_MainWindow):
    """Replacement main window when Clumzy Mode is on. Does not construct Scanner or Killer."""

    clumzy_mode_shell = True

    def __init__(self, window_icon=None):
        super().__init__()
        self.version = '1.29'
        self.shell_icon = window_icon or load_shell_window_icon()
        if qicon_is_empty(self.shell_icon):
            self.shell_icon = load_application_qicon()
        self.icon = load_application_qicon(LOGO_UI_CONTENT_FRACTION)
        if qicon_is_empty(self.icon):
            self.icon = self.processIcon(app_icon, crop_margins=True)
        if qicon_is_empty(self.shell_icon):
            self.shell_icon = self.icon
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
        self.BUTTON_ACTIVE_STYLE = (
            'background-color: #c0392b; color: white; font-weight: bold;'
        )
        self.BUTTON_NORMAL_STYLE = ''

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
        self.lblcenter.setText('')
        self._status_strip_plain = None
        self._status_strip_color = 'white'
        self._lag_in_allow_phase = False
        self._phase_deadline = 0.0

        self.lblleft.setWordWrap(False)
        self.lblleft.setMaximumHeight(self.lblleft.fontMetrics().height() + 6)
        self.lblleft.setAutoFillBackground(False)
        self.lblleft.setTextFormat(Qt.PlainText)
        self.gridLayout.addWidget(self.lblleft, 3, 1, 1, 2)
        self.lblright.setText('0 devices')

        self.btnScanEasy.setShortcut(QKeySequence())
        self.btnScanEasy.setText('')
        self.btnScanHard.setText('')
        self.btnSettings.setText('')
        for btn, btn_func, btn_icon, btn_tip in (
            (
                self.btnScanEasy,
                self.refresh_hotspot_table,
                scan_easy_icon,
                'Refresh hotspot clients (display only). Shortcut: Space.',
            ),
            (
                self.btnScanHard,
                None,
                scan_hard_icon,
                'Ping scan is not used in Clumzy Mode.',
            ),
            (
                self.btnSettings,
                self.openSettings,
                settings_icon,
                'Settings — turn Clumzy Mode off to return to normal ZubCut.',
            ),
            (
                self.btnAbout,
                self.openAbout,
                None,
                f'About {APP_DISPLAY_NAME}',
            ),
        ):
            btn.setToolTip(btn_tip)
            if btn_func is not None:
                btn.clicked.connect(btn_func)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setAttribute(Qt.WA_StyledBackground, True)
            if btn_icon is not None:
                btn.setIcon(self.processIcon(btn_icon))
        self.btnAbout.setIcon(self.icon)
        self._dim_unavailable_control(
            self.btnScanHard,
            'Ping scan is not used in Clumzy Mode.',
        )
        self.tableScan.setToolTip(
            'Display only. Kill, Lag Switch, Dupe, and Percent Cut apply to all hotspot traffic.'
        )

        sc_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc_space.setContext(Qt.WindowShortcut)
        sc_space.setAutoRepeat(False)
        sc_space.activated.connect(self.refresh_hotspot_table)

        self._flow = None  # None | 'kill' | 'lag' | 'dupe' | 'pctcut'
        self._build_flow_buttons()
        self.pgbar.setVisible(False)
        self.gridLayout.setSpacing(4)
        self.gridLayout.setVerticalSpacing(4)
        self.setMinimumSize(QSize(800, 560))

        self.tableScan.setColumnCount(len(TABLE_HEADER_LABELS))
        self.tableScan.verticalHeader().setVisible(False)
        self.tableScan.setHorizontalHeaderLabels(TABLE_HEADER_LABELS)
        self.tableScan.setSelectionMode(QAbstractItemView.NoSelection)
        self.tableScan.setFocusPolicy(Qt.NoFocus)
        self.tableScan.setItemDelegate(TableRowNoCellFocusDelegate(self.tableScan))
        self.tableScan.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._apply_scan_table_column_layout()

        self.settings_window = Settings(self, self.shell_icon)
        self.about_window = About(self, self.shell_icon)
        self.advanced_lag_settings_dialog = AdvancedLagSettingsDialog(self)
        self.advanced_lag_settings_dialog._clumzy_engine_host = self

        self._engine = None
        self._engine_error = ''
        try:
            self._engine = load_clumzy_engine()
            self._engine.set_network(NETWORK_REMOTE)
        except Exception as exc:
            self._engine_error = str(exc)

        self._flow = None  # None | 'kill' | 'lag' | 'dupe' | 'pctcut'
        self._want_running = False
        self._repeat_active = False
        self._adv_live = False
        self._op_busy = False
        self.mitm_shaping_active = False
        self.mitm_shaping_mac = ''
        self._mitm_adv_sched_t0 = 0.0
        self._mitm_adv_row_t0 = {}
        self._mitm_adv_last_sched = None
        self._shortcut_label_kill = 'L'
        self._shortcut_label_lag = 'M'
        self._shortcut_label_dupe = 'P'
        self._shortcut_label_pctcut = 'K'
        self._btn_kill_tooltip_static = (
            'Kill — Freeze all hotspot forwarded packets. Shortcut: L.'
        )
        self.auto_stop = QTimer(self)
        self.auto_stop.setSingleShot(True)
        self.auto_stop.timeout.connect(self._on_timer_elapsed)
        self._cycle_timer = QTimer(self)
        self._cycle_timer.setSingleShot(True)
        self._cycle_timer.timeout.connect(self._finish_cycle_restart)
        self._countdown_ui = QTimer(self)
        self._countdown_ui.setInterval(50)
        self._countdown_ui.timeout.connect(self._tick_flow_countdown)
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
        self._shortcut_pctcut = QShortcut(QKeySequence(Qt.Key_K), self)
        self._shortcut_pctcut.setContext(Qt.ApplicationShortcut)
        self._shortcut_pctcut.setAutoRepeat(False)
        self._shortcut_pctcut.activated.connect(self.toggle_percent_cut)
        self.refresh_keyboard_shortcuts_from_settings()

        apply_app_global_dark_stylesheet()
        self._repolish_chrome_pushbuttons()
        setup_frameless_main_window(self, title, self.shell_icon, maximizable=True)
        sync_translucent_chrome(
            [self, self.settings_window, self.about_window, self.advanced_lag_settings_dialog]
        )
        self._apply_inline_panel_styles()
        self._paint_buttons()
        _chrome_btns = (
            self.btnScanEasy,
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
        self.refresh_hotspot_table()
        if self._engine_error:
            self._log(self._engine_error, 'red')
        else:
            self._log(
                'Clumzy Mode ready. Right-click Kill / Lag / Dupe / Percent Cut for Advanced Lag.',
                'white',
            )

    def _build_flow_buttons(self) -> None:
        self.btnKill = QPushButton(self.centralwidget)
        self.btnKill.setObjectName('btnKill')
        self.btnKill.setAttribute(Qt.WA_StyledBackground, True)
        self.btnKill.setAutoDefault(False)
        self.btnKill.setDefault(False)
        self.btnKill.setMinimumHeight(88)
        self.btnKill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._btn_kill_icon = self.processIcon(kill_icon)
        self.btnKill.setIcon(self._btn_kill_icon)
        self.btnKill.setMinimumWidth(130)
        self.btnKill.setIconSize(QSize(56, 56))
        kill_font = QFont(self.btnKill.font())
        kill_font.setPointSize(13)
        kill_font.setBold(True)
        self.btnKill.setFont(kill_font)
        self.btnKill.setToolTip(
            'Kill — Freeze all hotspot forwarded packets. Shortcut: L.'
        )
        self.btnKill.pressed.connect(self.toggle_kill)

        self.btnLagSwitch = QPushButton('Lag Switch', self.centralwidget)
        self.btnLagSwitch.setObjectName('btnLagSwitch')
        self.btnLagSwitch.setAttribute(Qt.WA_StyledBackground, True)
        self.btnLagSwitch.setAutoDefault(False)
        self.btnLagSwitch.setDefault(False)
        self.btnLagSwitch.setMinimumHeight(72)
        self.btnLagSwitch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lag_font = QFont(self.btnLagSwitch.font())
        lag_font.setPointSize(13)
        lag_font.setBold(True)
        self.btnLagSwitch.setFont(lag_font)
        self.btnLagSwitch.setToolTip(
            'Lag Switch — Freeze for Lag ms, then pause for Normal ms (repeat). Shortcut: M.'
        )
        self.btnLagSwitch.pressed.connect(self.toggle_lag)

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
            'Dupe — Freeze for the duration, then stop (no repeat). Shortcut: P.'
        )
        self.btnDupe.pressed.connect(self.toggle_dupe)

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
        self.lblLagNormal = QLabel('Normal', self.groupLagInline)
        self.lagTimingRow.addWidget(self.lblLagNormal)
        self.normalSpinMain = QSpinBox(self.groupLagInline)
        self.normalSpinMain.setRange(1, 2147483647)
        self.normalSpinMain.setSingleStep(25)
        self.normalSpinMain.setValue(self._lag_allow_ms())
        self.normalSpinMain.setSuffix(' ms')
        self.lagTimingRow.addWidget(self.normalSpinMain)
        allow_tip = (
            'Allow/pause between Lag repeats is locked to Clumzy\'s '
            f'{self._lag_allow_ms()} ms settle.'
        )
        self._dim_unavailable_control(self.lblLagNormal, allow_tip)
        self._dim_unavailable_control(self.normalSpinMain, allow_tip)
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
            lambda checked: checked
            and (self.lagDirIncoming.setChecked(False), self.lagDirOutgoing.setChecked(False))
        )
        self.lagDirRow.setSpacing(6)
        self.lagDirRow.addWidget(QLabel('Block', self.groupLagInline))
        self.lagDirRow.addWidget(self.lagDirBoth)
        _lag_dir_sep = QFrame(self.groupLagInline)
        _lag_dir_sep.setFrameShape(QFrame.NoFrame)
        _lag_dir_sep.setFixedSize(1, 18)
        _lag_dir_sep.setStyleSheet(
            'background-color: #316E69; border-radius: 1px; margin-left: 10px; margin-right: 8px;'
        )
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
            lambda checked: checked
            and (self.dupeDirIncoming.setChecked(False), self.dupeDirOutgoing.setChecked(False))
        )
        self.dupeDirRow.setSpacing(6)
        self.dupeDirRow.addWidget(QLabel('Block', self.groupDupeInline))
        self.dupeDirRow.addWidget(self.dupeDirBoth)
        _dupe_dir_sep = QFrame(self.groupDupeInline)
        _dupe_dir_sep.setFrameShape(QFrame.NoFrame)
        _dupe_dir_sep.setFixedSize(1, 18)
        _dupe_dir_sep.setStyleSheet(
            'background-color: #316E69; border-radius: 1px; margin-left: 10px; margin-right: 8px;'
        )
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
            'Percent Cut — drop that percent of hotspot forwarded packets. Shortcut: K.'
        )
        self.gridLayout.addWidget(self.btnPercentCut, 7, 6, 1, 3)
        self.btnPercentCut.pressed.connect(self.toggle_percent_cut)
        for _flow_btn in (self.btnKill, self.btnLagSwitch, self.btnDupe, self.btnPercentCut):
            _flow_btn.setContextMenuPolicy(Qt.CustomContextMenu)
            _flow_btn.customContextMenuRequested.connect(self._on_main_flow_toggle_context_menu)

        self.sliderPercentCutMain.valueChanged.connect(self.spinPercentCutMain.setValue)
        self.spinPercentCutMain.valueChanged.connect(self.sliderPercentCutMain.setValue)
        self.spinPercentCutMain.valueChanged.connect(self._on_percent_cut_value_changed)
        self.sliderPercentCutMain.setValue(self._percent_cut_value())

        try:
            self.lagSpinMain.setValue(int(get_settings('clumzy_lag_timer_ms') or 9000))
        except Exception:
            pass
        try:
            self.dupeSpinMain.setValue(int(get_settings('clumzy_dupe_timer_ms') or 5000))
        except Exception:
            pass
        self.lagSpinMain.valueChanged.connect(self._persist_timers)
        self.dupeSpinMain.valueChanged.connect(self._persist_timers)

    @staticmethod
    def _lag_allow_ms() -> int:
        return max(1, int(CYCLE_SETTLE_S * 1000))

    def _persist_timers(self, *_args) -> None:
        try:
            set_settings_many(
                {
                    'clumzy_lag_timer_ms': int(self.lagSpinMain.value()),
                    'clumzy_dupe_timer_ms': int(self.dupeSpinMain.value()),
                }
            )
        except Exception:
            pass

    @staticmethod
    def processIcon(icon_data, crop_margins=False):
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

    def _apply_scan_table_column_layout(self):
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
        app = QApplication.instance()
        if app is None:
            return
        st = app.style()
        for w in (
            self.btnScanEasy,
            self.btnSettings,
            self.btnAbout,
            self.btnKill,
            self.btnLagSwitch,
            self.btnDupe,
            self.btnPercentCut,
        ):
            st.unpolish(w)
            st.polish(w)

    def _restore_chrome_button_surface(self, btn):
        try:
            if btn is self.btnSettings:
                self._sync_settings_gear_update_hint()
            elif btn is self.btnKill:
                self._updateKillButtonState()
            elif btn is self.btnLagSwitch:
                self._updateLagSwitchButtonState()
            elif btn is self.btnDupe:
                self._updateDupeButtonState()
            elif btn is self.btnPercentCut:
                self._updatePercentCutButtonState()
            else:
                btn.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        except RuntimeError:
            pass

    def _apply_status_strip_elide(self):
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
        self.lblleft.setStyleSheet(
            f'QLabel#lblleft {{ color: {hex_color}; background: transparent; border: none; }}'
        )
        self.lblleft.setAutoFillBackground(False)
        self.lblleft.setText(elided)

    def log(self, msg, color: str = 'white') -> None:
        plain = str(msg or '')
        self._status_strip_plain = plain
        self._status_strip_color = color
        self.lblleft.setToolTip(plain)
        self._apply_status_strip_elide()
        QTimer.singleShot(0, self._apply_status_strip_elide)

    def _log(self, msg, color: str = 'white') -> None:
        self.log(msg, color)

    def _sync_settings_gear_update_hint(self) -> None:
        return

    def _dim_unavailable_control(self, widget, tip: str) -> None:
        """Grey out a control that has no Clumzy Mode backend."""
        if widget is None:
            return
        widget.setEnabled(False)
        widget.setToolTip(tip)
        dim = QGraphicsOpacityEffect(widget)
        dim.setOpacity(0.38)
        widget.setGraphicsEffect(dim)

    def _on_main_flow_toggle_context_menu(self, pos) -> None:
        w = self.sender()
        if w is None:
            return
        menu = QMenu(self)
        theme_popup_menu(menu)
        act_adv = QAction('Advanced Lag Settings…', self)
        act_adv.triggered.connect(self.open_advanced_lag)
        menu.addAction(act_adv)
        menu.exec_(w.mapToGlobal(pos))

    def _direction_from_checks(self, both_cb, in_cb, out_cb) -> str:
        if in_cb.isChecked() and not out_cb.isChecked():
            return 'in'
        if out_cb.isChecked() and not in_cb.isChecked():
            return 'out'
        return 'both'

    def _inbound_outbound(self, direction: str) -> tuple[int, int]:
        if direction == 'in':
            return 1, 0
        if direction == 'out':
            return 0, 1
        return 1, 1

    @staticmethod
    def _format_countdown_ms(left_ms: int) -> str:
        left_ms = max(0, int(left_ms))
        sec = left_ms / 1000.0
        if sec >= 60:
            whole = int(sec)
            m, s = divmod(whole, 60)
            return f'Time left: {m}:{s:02d}'
        return f'Time left: {sec:.2f}s'

    def _apply_inline_panel_styles(self) -> None:
        sel_bg = UI_TABLE_SELECTION_BG
        admin_bg = ADMIN_DEVICE_TABLE_ROW_BG
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

    def _set_kill_button_idle_look(self) -> None:
        self.btnKill.setIcon(self._btn_kill_icon)
        self.btnKill.setIconSize(QSize(56, 56))
        self.btnKill.setMinimumWidth(130)

    def _set_kill_button_active_look(self) -> None:
        self.btnKill.setIcon(QIcon())
        self.btnKill.setMinimumWidth(1)

    def _updateKillButtonState(self, *, fast: bool = False) -> None:
        del fast
        if self._flow == 'kill':
            key = getattr(self, '_shortcut_label_kill', 'L')
            self._set_kill_button_active_look()
            self.btnKill.setText(f'■ KILL: ON\n(Press {key} to turn off)')
            self.btnKill.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
            return
        self._set_kill_button_idle_look()
        self.btnKill.setText('Kill: OFF')
        self.btnKill.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        if getattr(self, '_btn_kill_tooltip_static', None):
            self.btnKill.setToolTip(self._btn_kill_tooltip_static)

    def _updateLagSwitchButtonState(self) -> None:
        if self._flow == 'lag':
            key = getattr(self, '_shortcut_label_lag', 'M')
            self.btnLagSwitch.setText(f'■ LAGGING (Press {key} to turn off)')
            self.btnLagSwitch.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnLagSwitch.setText('Lag Switch')
            self.btnLagSwitch.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self._sync_inline_flow_controls_enabled()

    def _updateDupeButtonState(self) -> None:
        if self._flow == 'dupe':
            key = getattr(self, '_shortcut_label_dupe', 'P')
            self.btnDupe.setText(f'■ DUPE (Press {key} to turn off)')
            self.btnDupe.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnDupe.setText('Dupe')
            self.btnDupe.setStyleSheet(self.BUTTON_NORMAL_STYLE)
        self._sync_inline_flow_controls_enabled()

    @staticmethod
    def _clamp_percent(value) -> int:
        try:
            return max(1, min(100, int(value)))
        except Exception:
            return 100

    def _percent_cut_value(self) -> int:
        try:
            return self._clamp_percent(get_settings('traffic_percent'))
        except Exception:
            return 50

    def _on_percent_cut_value_changed(self, value) -> None:
        pct = self._clamp_percent(value)
        try:
            set_settings('traffic_percent', int(pct))
        except Exception:
            pass
        if getattr(self, '_flow', None) == 'pctcut':
            err = self._apply_percent_cut_engine(pct)
            if err:
                self._log(err, 'red')
        if hasattr(self, 'btnPercentCut'):
            self._updatePercentCutButtonState()

    def _updatePercentCutButtonState(self) -> None:
        pct = self._clamp_percent(self.spinPercentCutMain.value())
        key = getattr(self, '_shortcut_label_pctcut', 'K')
        if self._flow == 'pctcut':
            self.btnPercentCut.setText(f'■ CUT {pct}% (Press {key} to turn off)')
            self.btnPercentCut.setStyleSheet(self.BUTTON_ACTIVE_STYLE)
        else:
            self.btnPercentCut.setText(f'Percent Cut: {pct}%')
            self.btnPercentCut.setStyleSheet(self.BUTTON_NORMAL_STYLE)

    def _sync_inline_flow_controls_enabled(self) -> None:
        lag_locked = getattr(self, '_flow', None) == 'lag'
        self.lagDirBoth.setEnabled(not lag_locked)
        self.lagDirIncoming.setEnabled(not lag_locked)
        self.lagDirOutgoing.setEnabled(not lag_locked)
        dupe_locked = getattr(self, '_flow', None) == 'dupe'
        self.dupeDirBoth.setEnabled(not dupe_locked)
        self.dupeDirIncoming.setEnabled(not dupe_locked)
        self.dupeDirOutgoing.setEnabled(not dupe_locked)

    def _paint_buttons(self) -> None:
        self._updateKillButtonState()
        self._updateLagSwitchButtonState()
        self._updateDupeButtonState()
        self._updatePercentCutButtonState()

    def stopLagSwitch(self) -> None:
        self._stop_engine()

    def stopDupe(self, log: bool = False) -> None:
        del log
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
        n = len(rows)
        self.lblright.setText(f'{n} devices')
        self.lblcenter.setText('')

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
        try:
            s = import_settings()
        except Exception:
            s = {}
        k_kill = keyseq_from_setting(s.get('key_kill'), Qt.Key_L)
        k_lag = keyseq_from_setting(s.get('key_lag'), Qt.Key_M)
        k_dupe = keyseq_from_setting(s.get('key_dupe'), Qt.Key_P)
        k_pct = keyseq_from_setting(s.get('key_pctcut'), Qt.Key_K)
        self._shortcut_kill.setKey(k_kill)
        self._shortcut_lag.setKey(k_lag)
        self._shortcut_dupe.setKey(k_dupe)
        self._shortcut_pctcut.setKey(k_pct)
        nk = k_kill.toString(QKeySequence.NativeText)
        nl = k_lag.toString(QKeySequence.NativeText)
        np = k_dupe.toString(QKeySequence.NativeText)
        nk_pct = k_pct.toString(QKeySequence.NativeText)
        self._shortcut_label_kill = nk or 'L'
        self._shortcut_label_lag = nl or 'M'
        self._shortcut_label_dupe = np or 'P'
        self._shortcut_label_pctcut = nk_pct or 'K'
        self._btn_kill_tooltip_static = (
            'Kill — Freeze all hotspot forwarded packets. Shortcut: %s.' % nk
        )
        self.btnKill.setToolTip(self._btn_kill_tooltip_static)
        self.btnLagSwitch.setToolTip(
            'Lag Switch — Freeze for Lag ms, then pause for Normal ms (repeat). Shortcut: %s.'
            % nl
        )
        self.btnDupe.setToolTip(
            'Dupe — Freeze for the duration, then stop (no repeat). Shortcut: %s.' % np
        )
        self.btnPercentCut.setToolTip(
            'Percent Cut — drop that percent of hotspot forwarded packets. Shortcut: %s.'
            % nk_pct
        )
        self._paint_buttons()

    def _ensure_engine(self) -> bool:
        if self._engine is None:
            self._log(self._engine_error or 'Clumzy engine is not available.', 'red')
            return False
        return True

    def _hide_flow_countdowns(self) -> None:
        self._countdown_ui.stop()
        self.lblLagCountdownMain.setVisible(False)
        self.lblDupeCountdownMain.setVisible(False)
        self.lblLagCountdownMain.setText('')
        self.lblDupeCountdownMain.setText('')

    def _arm_countdown(self, ms: int) -> None:
        self._phase_deadline = time.monotonic() + max(1, int(ms)) / 1000.0
        self._countdown_ui.start()
        self._tick_flow_countdown()

    def _tick_flow_countdown(self) -> None:
        left = int(max(0.0, self._phase_deadline - time.monotonic()) * 1000)
        text = self._format_countdown_ms(left)
        if self._flow == 'lag':
            self.lblLagCountdownMain.setText(text)
            self.lblLagCountdownMain.setVisible(True)
            self.lblDupeCountdownMain.setVisible(False)
        elif self._flow == 'dupe':
            self.lblDupeCountdownMain.setText(text)
            self.lblDupeCountdownMain.setVisible(True)
            self.lblLagCountdownMain.setVisible(False)
        else:
            self._hide_flow_countdowns()

    def _stop_engine(self) -> None:
        self.auto_stop.stop()
        self._cycle_timer.stop()
        self._want_running = False
        self._repeat_active = False
        self._lag_in_allow_phase = False
        self._adv_live = False
        self.mitm_shaping_active = False
        self._adv_timer.stop()
        self._hide_flow_countdowns()
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass
        self._flow = None
        self._paint_buttons()

    def _start_freeze(self, direction: str = 'both') -> str | None:
        if not self._ensure_engine():
            return self._engine_error or 'no engine'
        inn, out = self._inbound_outbound(direction)
        apply_freeze(self._engine, inbound=inn, outbound=out)
        self._engine.set_network(NETWORK_REMOTE)
        return self._engine.start(FILTER)

    def _apply_percent_cut_engine(self, pct: int) -> str | None:
        if not self._ensure_engine():
            return self._engine_error or 'no engine'
        chance = float(self._clamp_percent(pct))
        self._engine.drop(1, 1, chance)
        self._engine.enable('drop', True)
        self._engine.enable('lag', False)
        for name in (
            'disconnect',
            'bandwidth',
            'throttle',
            'duplicate',
            'ood',
            'tamper',
            'reset',
        ):
            self._engine.enable(name, False)
        self._engine.set_network(NETWORK_REMOTE)
        if not self._engine.is_running():
            return self._engine.start(FILTER)
        return None

    def toggle_kill(self) -> None:
        if self._flow == 'kill':
            self._stop_engine()
            self._log('Kill OFF.', UI_LOG_RESTORE_FG)
            return
        self._stop_engine()
        err = self._start_freeze('both')
        if err:
            self._log(err, 'red')
            return
        self._flow = 'kill'
        self._want_running = True
        self._paint_buttons()
        self._log('Kill ON — freeze on all hotspot forwarded packets.', UI_LOG_VICTIM_BLOCK_FG)

    def toggle_lag(self) -> None:
        if self._flow == 'lag':
            self._stop_engine()
            self._log('Lag Switch OFF.', UI_LOG_RESTORE_FG)
            return
        direction = self._direction_from_checks(
            self.lagDirBoth, self.lagDirIncoming, self.lagDirOutgoing
        )
        self._stop_engine()
        err = self._start_freeze(direction)
        if err:
            self._log(err, 'red')
            return
        lag_ms = max(1, int(self.lagSpinMain.value()))
        self._flow = 'lag'
        self._want_running = True
        self._repeat_active = True
        self._lag_in_allow_phase = False
        self.auto_stop.start(lag_ms)
        self._arm_countdown(lag_ms)
        self._paint_buttons()
        dir_text = {'both': 'all', 'in': 'incoming', 'out': 'outgoing'}[direction]
        self._log(
            f'Lag switch ON: {lag_ms}ms lag ({dir_text}) / {self._lag_allow_ms()}ms allow (locked)',
            UI_LOG_VICTIM_BLOCK_FG,
        )

    def toggle_dupe(self) -> None:
        if self._flow == 'dupe':
            self._stop_engine()
            self._log('Dupe OFF.', UI_LOG_RESTORE_FG)
            return
        direction = self._direction_from_checks(
            self.dupeDirBoth, self.dupeDirIncoming, self.dupeDirOutgoing
        )
        self._stop_engine()
        err = self._start_freeze(direction)
        if err:
            self._log(err, 'red')
            return
        dur = max(1, int(self.dupeSpinMain.value()))
        self._flow = 'dupe'
        self._want_running = True
        self._repeat_active = False
        self.auto_stop.start(dur)
        self._arm_countdown(dur)
        self._paint_buttons()
        self._log(f'Dupe ON — {dur}ms then stop.', UI_LOG_VICTIM_BLOCK_FG)

    def toggle_percent_cut(self) -> None:
        if self._flow == 'pctcut':
            self._stop_engine()
            self._log('Percent Cut OFF.', UI_LOG_RESTORE_FG)
            return
        pct = self._clamp_percent(self.spinPercentCutMain.value())
        self._stop_engine()
        err = self._apply_percent_cut_engine(pct)
        if err:
            self._log(err, 'red')
            return
        self._flow = 'pctcut'
        self._want_running = True
        self._paint_buttons()
        self._log(f'Percent Cut ON — drop {pct}%.', UI_LOG_VICTIM_BLOCK_FG)

    def _on_timer_elapsed(self) -> None:
        if self._flow == 'lag' and self._want_running and self._repeat_active:
            if self._engine is not None:
                try:
                    self._engine.stop()
                except Exception:
                    pass
            self._lag_in_allow_phase = True
            settle = self._lag_allow_ms()
            self._cycle_timer.start(settle)
            self._arm_countdown(settle)
            return
        self._stop_engine()
        self._log('Timer finished.', UI_LOG_RESTORE_FG)

    def _finish_cycle_restart(self) -> None:
        if not (self._flow == 'lag' and self._want_running and self._repeat_active):
            return
        direction = self._direction_from_checks(
            self.lagDirBoth, self.lagDirIncoming, self.lagDirOutgoing
        )
        err = self._start_freeze(direction)
        if err:
            self._stop_engine()
            self._log(err, 'red')
            return
        self._lag_in_allow_phase = False
        lag_ms = max(1, int(self.lagSpinMain.value()))
        self.auto_stop.start(lag_ms)
        self._arm_countdown(lag_ms)

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
