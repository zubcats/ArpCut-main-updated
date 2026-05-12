from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLineEdit,
    QLabel,
    QPushButton,
    QKeySequenceEdit,
    QCheckBox,
)
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtCore import Qt, QTimer
import os
import sys

from tools.utils_gui import import_settings, export_settings, get_settings, \
                      is_admin, add_to_startup, remove_from_startup, set_settings, \
                      zubcut_dark_stylesheet, \
                      sync_translucent_chrome, register_window_surface_effects, \
                      repair_settings
from tools.frameless_chrome import FramelessResizableMixin, setup_frameless_main_window
from tools.qtools import MsgType, Buttons
from tools.utils import (
    goto,
    get_ifaces,
    get_default_iface,
    get_iface_by_name,
    terminal,
    format_iface_settings_label,
)

from ui.ui_settings import Ui_MainWindow

from networking.nicknames import Nicknames

from tools.keybinds import keyseq_from_setting
from tools.updater_core import get_update_status, launch_installer, selected_update_url
from tools.updater_progress import download_update_with_progress_dialog
from tools.updater_debug import (
    begin_updater_debug_session,
    updater_log,
    updater_log_paths_hint,
)

from constants import *
import constants as _zcut_constants

from tools.clumsy_inline import clumsy_bundle_offered, windivert_driver_installed
from tools.clumsy_ics import ensure_clumsy_ics_enabled, rollback_clumsy_ics
from tools.utils_gui import restart_zubcut

_UPDATE_BTN_QSS_FALLBACK = (
    'QPushButton#btnUpdate { background-color: #1a3d28; color: #d8f0e4; font-weight: bold; '
    'border: 1px solid #2d5738; border-radius: 4px; }'
)


def _coerce_scan_counts(s: dict) -> dict:
    """count/threads must be ints in range; bad JSON or types would break range() / ThreadPool."""
    out = dict(s) if s else {}
    for key, default, lo, hi in (
        ('count', 25, 25, 255),
        ('threads', 12, 5, 255),
    ):
        try:
            v = int(out.get(key, default))
            out[key] = max(lo, min(hi, v))
        except (TypeError, ValueError):
            out[key] = default
    return out


def _settings_keybind_mono_font() -> QFont:
    """Match main #tableScan: readable monospace, normal weight (Fusion/qdark often bolds shortcuts)."""
    mono = 'Menlo' if sys.platform == 'darwin' else 'Consolas'
    f = QFont(mono, 11)
    f.setStyleHint(QFont.Monospace)
    f.setFixedPitch(True)
    f.setBold(False)
    return f


def _channel_kind_label(channel: str) -> str:
    """User-facing build line (avoid internal names like 'stable' in dialogs)."""
    c = str(channel or '').strip().lower()
    if c == 'experimental':
        return 'Experimental / testing build'
    return 'Regular ZubCut release'


class Settings(FramelessResizableMixin, QMainWindow, Ui_MainWindow):
    def __init__(self, elmocut, icon):
        super().__init__()
        self.elmocut = elmocut

        # Setup UI
        self.icon = icon
        self.setWindowIcon(icon)
        self.setupUi(self)
        self.setObjectName('zubcutAuxiliaryWindow')
        self._install_percent_keybind_row()
        self._install_clumsy_controls()
        if str(UPDATE_CHANNEL or '').strip().lower() in ('paid', 'experimental'):
            self.setMaximumSize(
                self.maximumSize().width(),
                self.maximumSize().height() + 48,
            )
            self.btnPaidSignIn = QPushButton('Sign in or change license…', self.centralwidget)
            self.btnPaidSignIn.setObjectName('btnPaidSignIn')
            self.btnPaidSignIn.setMinimumHeight(34)
            self.gridLayout.addWidget(self.btnPaidSignIn, 7, 0, 1, 4)
            self.btnPaidSignIn.clicked.connect(self._on_paid_sign_in)
        self.adjustSize()
        self.setFixedSize(self.size())

        self.loadInterfaces()

        # Apply old settings on open
        self.currentSettings()

        self.sliderCount.valueChanged.connect(self.spinCount.setValue)
        self.spinCount.valueChanged.connect(self.sliderCount.setValue)
        self.sliderThreads.valueChanged.connect(self.spinThreads.setValue)
        self.spinThreads.valueChanged.connect(self.sliderThreads.setValue)
        self.btnApply.clicked.connect(self.Apply)
        self.btnDefaults.clicked.connect(self.Defaults)
        self.btnUpdate.clicked.connect(self.checkUpdate)
        channel = str(UPDATE_CHANNEL or 'experimental').strip().lower()
        if channel not in ('stable', 'experimental'):
            channel = 'experimental'
        self._update_channel = channel
        self._update_published_label = ''
        self._update_available = False
        self.btnUpdate.setText(self._update_button_text())
        # Defer first HEAD check so it does not run synchronously during main window construction.
        QTimer.singleShot(0, self._deferred_initial_update_check)
        QTimer.singleShot(0, self._refresh_clumsy_settings_widgets)
        self.chkAutoupdate.setToolTip(
            'Automatic startup updates are not used. Use Install Latest Build below when you want to update.'
        )
        # Deprecated/unused: remove from UI to avoid confusion.
        self.chkAutoupdate.hide()
        # Killed-device persistence is deprecated: always off (users can re-kill manually).
        self.chkRemember.hide()
        self.chkRemember.setEnabled(False)

        setup_frameless_main_window(self, self.windowTitle(), self.icon, maximizable=False)
        register_window_surface_effects(self)

    def _install_clumsy_controls(self):
        self.chkClumsy = QCheckBox('Clumsy Mode', self.gridLayoutWidget_2)
        self.chkClumsy.setToolTip('')
        self.btnClumsyInstall = QPushButton('Install Clumsy mode…', self.gridLayoutWidget_2)
        self.btnClumsyInstall.setToolTip(
            'Downloads the latest experimental installer (includes optional WinDivert setup).'
        )
        self.gridLayout_3.addWidget(self.chkClumsy, 2, 0, 1, 2)
        self.gridLayout_3.addWidget(self.btnClumsyInstall, 2, 2, 1, 2)
        self.groupBox_3.setMinimumHeight(150)
        self.gridLayoutWidget_2.setMinimumHeight(100)
        # Clumsy row adds vertical pressure; increase keybind group height to keep labels readable.
        self.groupBox_keys.setMinimumHeight(140)
        self._clumsy_toggle_guard = False
        self.chkClumsy.stateChanged.connect(self._on_clumsy_checkbox_changed)
        self.btnClumsyInstall.clicked.connect(self._on_clumsy_install_clicked)

    def _refresh_clumsy_settings_widgets(self):
        if not sys.platform.startswith('win'):
            self.chkClumsy.hide()
            self.btnClumsyInstall.hide()
            return
        bundle = clumsy_bundle_offered()
        driver_ok = windivert_driver_installed()
        if bundle and driver_ok:
            self.btnClumsyInstall.hide()
            self.chkClumsy.show()
        else:
            self.chkClumsy.hide()
            self.btnClumsyInstall.show()

    def _on_clumsy_checkbox_changed(self, _state):
        if self._clumsy_toggle_guard:
            return
        if not self.chkClumsy.isVisible():
            return
        new_v = self.chkClumsy.isChecked()
        try:
            old_v = bool(get_settings('clumsy_mode'))
        except Exception:
            old_v = False
        if new_v == old_v:
            return
        if MsgType.WARN(
            self,
            'Restart ZubCut',
            'Changing Clumsy mode requires a full restart.\nRestart now?',
            Buttons.YES | Buttons.NO,
        ) == Buttons.NO:
            self._clumsy_toggle_guard = True
            self.chkClumsy.setChecked(old_v)
            self._clumsy_toggle_guard = False
            return
        if new_v:
            ok, detail = ensure_clumsy_ics_enabled()
            if not ok:
                MsgType.ERROR(
                    self,
                    'Clumsy Mode',
                    'Could not enable console sharing automatically.\n\n'
                    + (detail or 'Unknown error.'),
                    Buttons.OK,
                )
                self._clumsy_toggle_guard = True
                self.chkClumsy.setChecked(old_v)
                self._clumsy_toggle_guard = False
                return
            try:
                cur = (get_settings('iface') or '').strip()
            except Exception:
                cur = ''
            set_settings('iface_before_clumsy', cur)
        else:
            ok, detail = rollback_clumsy_ics()
            if not ok:
                MsgType.ERROR(
                    self,
                    'Clumsy Mode',
                    'Could not restore your previous sharing setup.\n\n'
                    + (detail or 'Unknown error.'),
                    Buttons.OK,
                )
                self._clumsy_toggle_guard = True
                self.chkClumsy.setChecked(old_v)
                self._clumsy_toggle_guard = False
                return
            try:
                prev = (get_settings('iface_before_clumsy') or '').strip()
            except Exception:
                prev = ''
            if prev:
                set_settings('iface', prev)
            set_settings('iface_before_clumsy', '')
        set_settings('clumsy_mode', new_v)
        restart_zubcut(self.elmocut)

    def _on_clumsy_install_clicked(self):
        url = (UPDATE_DOWNLOAD_URL_EXPERIMENTAL or '').strip()
        if not url:
            MsgType.WARN(
                self,
                'Download not configured',
                'No experimental installer URL is configured in this build.',
                Buttons.OK,
            )
            return
        if MsgType.WARN(
            None,
            'Install Clumsy mode',
            (
                'This downloads the latest experimental ZubCut installer '
                '(with optional WinDivert / Clumsy components).\n'
                'Continue?'
            ),
            Buttons.YES | Buttons.NO,
        ) == Buttons.NO:
            return
        try:
            path = download_update_with_progress_dialog(self, url)
            if path is None:
                return
            launch_installer(path)
            self.elmocut.quit_all()
        except Exception as e:
            MsgType.ERROR(
                None,
                'Download failed',
                f'Could not download installer.\n{e}',
                Buttons.OK,
            )

    def _install_percent_keybind_row(self):
        self.labelKeyPctCut = QLabel('Percent Cut toggle (main window)', self.groupBox_keys)
        self.keySeqPctCut = QKeySequenceEdit(self.groupBox_keys)
        self.keySeqPctCut.setObjectName('keySeqPctCut')
        self.formLayout_keys.addRow(self.labelKeyPctCut, self.keySeqPctCut)

    def _on_paid_sign_in(self):
        from gui.paid_license_signin import run_paid_license_signin
        from tools.license_offline import load_and_validate_installed_license

        if not run_paid_license_signin(self, self.icon):
            return
        if load_and_validate_installed_license().ok:
            MsgType.INFO(
                self,
                'License',
                'License saved. Restart ZubCut if the app still shows an old license message.',
            )
        else:
            MsgType.WARN(
                self,
                'License',
                'The file could not be verified. Try again or contact your administrator.',
            )

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_update_banner()
        el = getattr(self, 'elmocut', None)
        if el is not None and hasattr(el, '_sync_settings_gear_update_hint'):
            el._sync_settings_gear_update_hint()
        self._refresh_clumsy_settings_widgets()

    def Apply(self, silent_apply=False):
        repair_settings()
        nicknames = Nicknames()

        count         =  self.spinCount.value()
        threads       =  self.spinThreads.value()
        is_autostart  =  self.chkAutostart.isChecked()
        is_minimized  =  self.chkMinimized.isChecked()
        # Deprecated feature: never persist killed devices across restarts.
        is_remember   =  False
        is_autoupdate =  self.chkAutoupdate.isChecked()
        iface = self.comboInterface.currentData()
        if iface in (None, ''):
            iface = self.comboInterface.currentText()

        def _portable_key(ks_edit):
            qs = ks_edit.keySequence()
            if qs.isEmpty():
                return None
            return qs.toString(QKeySequence.PortableText)

        k_kill = _portable_key(self.keySeqKill)
        k_lag = _portable_key(self.keySeqLag)
        k_dupe = _portable_key(self.keySeqDupe)
        k_pct = _portable_key(self.keySeqPctCut)
        if not k_kill or not k_lag or not k_dupe or not k_pct:
            MsgType.WARN(
                self,
                'Keyboard shortcuts',
                'Each shortcut must have a key assigned.',
                Buttons.OK,
            )
            return
        if len({k_kill, k_lag, k_dupe, k_pct}) < 4:
            MsgType.WARN(
                self,
                'Keyboard shortcuts',
                'Kill, Lag Switch, Dupe, and Percent Cut shortcuts must all be different.',
                Buttons.OK,
            )
            return

        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.join(os.getcwd(), APP_EXE_NAME)
        if is_autostart:
            add_to_startup(exe_path)
        else:
            remove_from_startup()

        # Persistence removed: keep settings clean; killed devices are session-only.
        killed_all = []

        try:
            show_mac = bool(get_settings('show_scan_mac_column'))
            show_ven = bool(get_settings('show_scan_vendor_column'))
            traffic_pct = int(get_settings('traffic_percent'))
        except Exception:
            try:
                s0 = import_settings()
            except Exception:
                s0 = {}
            show_mac = bool(s0.get('show_scan_mac_column', False))
            show_ven = bool(s0.get('show_scan_vendor_column', False))
            try:
                traffic_pct = int(s0.get('traffic_percent', 50))
            except (TypeError, ValueError):
                traffic_pct = 50

        try:
            clumsy_mode = bool(get_settings('clumsy_mode'))
        except Exception:
            clumsy_mode = False

        try:
            iface_stash = str(get_settings('iface_before_clumsy') or '')
        except Exception:
            iface_stash = ''

        export_settings(
            [
            count,
            is_autostart,
            is_minimized,
            is_remember,
            killed_all,
            is_autoupdate,
            threads,
            iface,
            iface_stash,
            nicknames.nicknames_database,
            k_kill,
            k_lag,
            k_dupe,
            k_pct,
            show_mac,
            show_ven,
            traffic_pct,
            clumsy_mode,
            ]
        )

        old_iface = self.elmocut.scanner.iface.name
        
        self.elmocut.iface = get_iface_by_name(iface)
        self.updateElmocutSettings()
        # Fix horizontal headerfont reverts to normal after applying settings
        mono_font = 'Menlo' if __import__('sys').platform == 'darwin' else 'Consolas'
        self.elmocut.tableScan.horizontalHeader().setFont(QFont(mono_font, 11))

        if not silent_apply:
            MsgType.INFO(
                self,
                'Apply Settings',
                'New settings have been applied.'
            )
        
        if old_iface != iface:
            MsgType.INFO(
                self,
                'Interface Changed',
                f'{APP_DISPLAY_NAME} will restart to apply new interface.'
            )

            # Restart app via restart.exe
            __import__('os').system('start "" restart.exe')
            self.elmocut.quit_all()
        
        self.close()

    def Defaults(self):
        if MsgType.WARN(
            self,
            'Default settings',
            'All settings will be reset to default.\nAre you sure?',
            Buttons.YES | Buttons.NO
        ) == Buttons.NO:
            return
        
        nickname_prompt = MsgType.WARN(
            self,
            'Default settings',
            'Do you want to reset devices nicknames?',
            Buttons.YES | Buttons.NO
        )
        
        # Check if user wants to keep nicknames or not
        if nickname_prompt == Buttons.NO:
            nicknames = Nicknames()
            vals = SETTINGS_VALS[:]
            vals[SETTINGS_KEYS.index('nicknames')] = nicknames.nicknames_database
            export_settings(vals)
        else:
            export_settings()
        
        self.currentSettings()
        self.Apply()

    def updateElmocutSettings(self):
        repair_settings()
        s = _coerce_scan_counts(import_settings())
        self.currentSettings()
        
        self.elmocut.minimize = s['minimized']
        self.elmocut.remember = False
        self.elmocut.autoupdate = s['autoupdate']
        self.elmocut.scanner.device_count = s['count']
        self.elmocut.scanner.max_threads = s['threads']
        
        self.elmocut.scanner.iface = get_iface_by_name(s['iface'])
        self.elmocut.killer.iface = get_iface_by_name(s['iface'])
        
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(self.styleSheet())
        self.elmocut._repolish_chrome_pushbuttons()
        self.elmocut.setStyleSheet('')
        self.elmocut.about_window.setStyleSheet('')
        # Lag/Dupe must inherit QApplication styles only. A full app sheet copied onto QDialog
        # breaks QDialog-scoped rules from zubcut_dark_stylesheet() (qdark blue panels return).
        for _dlg in (
            getattr(self.elmocut, 'lag_switch_dialog', None),
            getattr(self.elmocut, 'dupe_switch_dialog', None),
        ):
            if _dlg is not None:
                _dlg.setStyleSheet('')
        _w = [
            self.elmocut,
            self.elmocut.about_window,
            self,
            self.elmocut.device_window,
            self.elmocut.traffic_window,
        ]
        _w.extend(d for d in (
            getattr(self.elmocut, 'lag_switch_dialog', None),
            getattr(self.elmocut, 'dupe_switch_dialog', None),
        ) if d is not None)
        sync_translucent_chrome(_w)
        self.elmocut.refresh_keyboard_shortcuts_from_settings()
        self.elmocut._sync_scan_table_column_settings()

    def currentSettings(self):
        s = _coerce_scan_counts(import_settings())
        self.chkAutostart.setChecked(s['autostart'])
        self.chkMinimized.setChecked(s['minimized'])
        self.chkRemember.setChecked(False)
        self.chkAutoupdate.setEnabled(False)
        self.chkAutoupdate.setChecked(False)
        self.spinCount.setValue(s['count'])
        self.spinThreads.setValue(s['threads'])
        self.sliderCount.setValue(s['count'])
        self.sliderThreads.setValue(s['threads'])
        
        if not s['iface']:
            set_settings('iface', get_default_iface().name)
            s = import_settings()
        
        saved = s.get('iface') or ''
        idx = self.comboInterface.findData(saved)
        if idx < 0:
            idx = self.comboInterface.findText(saved, Qt.MatchFixedString)
        if idx >= 0:
            self.comboInterface.setCurrentIndex(idx)

        self.keySeqKill.setKeySequence(keyseq_from_setting(s.get('key_kill'), Qt.Key_L))
        self.keySeqLag.setKeySequence(keyseq_from_setting(s.get('key_lag'), Qt.Key_M))
        self.keySeqDupe.setKeySequence(keyseq_from_setting(s.get('key_dupe'), Qt.Key_P))
        self.keySeqPctCut.setKeySequence(keyseq_from_setting(s.get('key_pctcut'), Qt.Key_K))

        try:
            clumsy_mode = bool(s.get('clumsy_mode', False))
        except Exception:
            clumsy_mode = False
        self._clumsy_toggle_guard = True
        self.chkClumsy.setChecked(clumsy_mode)
        self._clumsy_toggle_guard = False
        self._refresh_clumsy_settings_widgets()

        self._apply_keybind_section_fonts()
        self.setStyleSheet(zubcut_dark_stylesheet())

    def _apply_keybind_section_fonts(self):
        f = _settings_keybind_mono_font()
        for w in (
            self.groupBox_keys,
            self.labelKeyKill,
            self.labelKeyLag,
            self.labelKeyDupe,
            self.labelKeyPctCut,
            self.keySeqKill,
            self.keySeqLag,
            self.keySeqDupe,
            self.keySeqPctCut,
        ):
            w.setFont(f)
        for ks in (self.keySeqKill, self.keySeqLag, self.keySeqDupe, self.keySeqPctCut):
            for le in ks.findChildren(QLineEdit):
                le.setFont(f)
    
    def checkUpdate(self):
        begin_updater_debug_session('settings.checkUpdate')
        updater_log('checkUpdate: entered')
        url = selected_update_url()
        if not url:
            MsgType.WARN(
                self,
                'Update URL Missing',
                (
                    'This build is not configured with a download link for updates.\n'
                    '(Developers: set the matching UPDATE_DOWNLOAD_URL_* entry in src/constants.py.)'
                ),
                Buttons.OK,
            )
            return
        if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
            MsgType.WARN(
                self,
                'Invalid Update URL',
                (
                    'Update URL must start with http:// or https://\n'
                    f'Build: {_channel_kind_label(self._update_channel)}'
                ),
                Buttons.OK,
            )
            return

        # Parent=None: same frameless-window + modal child crash class as QProgressDialog on Windows.
        confirm = MsgType.WARN(
            None,
            'Install Latest Build',
            (
                f'This will install the latest {self._channel_label()} build.\n'
                'You will see download progress, then a setup window while it installs, '
                'and ZubCut will start again when finished.\n'
                'Continue?'
            ),
            Buttons.YES | Buttons.NO,
        )
        if confirm == Buttons.NO:
            updater_log('checkUpdate: user declined')
            return

        updater_log('checkUpdate: user confirmed, disabling button')
        self.btnUpdate.setEnabled(False)
        self.btnUpdate.setText('Downloading…')
        quit_for_update = False
        try:
            updater_log('checkUpdate: calling download_update_with_progress_dialog')
            path = download_update_with_progress_dialog(self, url)
            updater_log('checkUpdate: download returned path=%r', path)
            if path is None:
                return
            updater_log('checkUpdate: launch_installer')
            launch_installer(path)
            quit_for_update = True
            updater_log('checkUpdate: quit_all')
            self.elmocut.quit_all()
        except Exception as e:
            updater_log('checkUpdate: exception %s', e, exc_info=True)
            MsgType.ERROR(
                None,
                'Update Failed',
                (
                    f'Could not download/install update.\n{e}\n\n'
                    f'Details were appended to:\n{updater_log_paths_hint()}'
                ),
                Buttons.OK,
            )
        finally:
            # quit_all() destroys this window; touching widgets here crashes.
            if quit_for_update:
                return
            try:
                if self.isVisible():
                    self.btnUpdate.setEnabled(True)
                    self.btnUpdate.setText(self._update_button_text())
                    self._apply_update_button_style()
            except RuntimeError:
                pass

    def _channel_label(self):
        return 'experimental' if self._update_channel == 'experimental' else APP_DISPLAY_NAME

    def _deferred_initial_update_check(self):
        try:
            self._refresh_update_availability()
            self.btnUpdate.setText(self._update_button_text())
            self._apply_update_button_style()
            el = getattr(self, 'elmocut', None)
            if el is not None and hasattr(el, '_sync_settings_gear_update_hint'):
                el._sync_settings_gear_update_hint()
        except Exception:
            pass

    def _refresh_update_availability(self):
        """Fetch remote installer time; compare to embedded build time when CI set it."""
        self._update_available, self._update_published_label = get_update_status()

    def refresh_update_banner(self):
        """Re-fetch server state and refresh the update button (call after open or on a timer)."""
        try:
            self._refresh_update_availability()
            self.btnUpdate.setText(self._update_button_text())
            self._apply_update_button_style()
        except Exception:
            pass

    def apply_update_banner_state(self, available, published_label):
        """Apply a fetch done elsewhere (e.g. background thread) without another HEAD request."""
        try:
            self._update_available = bool(available)
            self._update_published_label = (published_label or '').strip()
            self.btnUpdate.setText(self._update_button_text())
            self._apply_update_button_style()
        except Exception:
            pass

    def _update_button_text(self):
        if self._update_channel == 'experimental':
            base = 'Install Latest Build (Experimental)'
        else:
            base = 'Install Latest Build'
        if self._update_available:
            base = f'New version available — {base}'
        if self._update_published_label:
            return f'{base} [{self._update_published_label}]'
        return base

    def _apply_update_button_style(self):
        if self._update_available:
            self.btnUpdate.setStyleSheet(
                getattr(_zcut_constants, 'UPDATE_AVAILABLE_PUSHBUTTON_QSS', _UPDATE_BTN_QSS_FALLBACK)
            )
        else:
            self.btnUpdate.setStyleSheet('')
    
    def loadInterfaces(self):
        self.comboInterface.clear()
        for iface in get_ifaces():
            self.comboInterface.addItem(
                format_iface_settings_label(iface),
                iface.name,
            )