from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtCore import Qt
import os
import sys

from tools.utils_gui import import_settings, export_settings, get_settings, \
                      is_admin, add_to_startup, remove_from_startup, set_settings, \
                      zubcut_dark_stylesheet, sync_translucent_chrome, register_window_surface_effects
from tools.frameless_chrome import FramelessResizableMixin, setup_frameless_main_window
from tools.qtools import MsgType, Buttons
from tools.utils import goto, get_ifaces, get_default_iface, get_iface_by_name, terminal

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

class Settings(FramelessResizableMixin, QMainWindow, Ui_MainWindow):
    def __init__(self, elmocut, icon):
        super().__init__()
        self.elmocut = elmocut

        # Setup UI
        self.icon = icon
        self.setWindowIcon(icon)
        self.setupUi(self)
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
        self.chkAutoupdate.setToolTip(
            'Automatic startup updates are not used. Use Install Latest Build below when you want to update.'
        )

        setup_frameless_main_window(self, self.windowTitle(), self.icon, maximizable=False)
        register_window_surface_effects(self)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_update_banner()
        el = getattr(self, 'elmocut', None)
        if el is not None and hasattr(el, '_sync_settings_gear_update_hint'):
            el._sync_settings_gear_update_hint()

    def Apply(self, silent_apply=False):
        nicknames = Nicknames()

        count         =  self.spinCount.value()
        threads       =  self.spinThreads.value()
        is_autostart  =  self.chkAutostart.isChecked()
        is_minimized  =  self.chkMinimized.isChecked()
        is_remember   =  self.chkRemember.isChecked()
        is_autoupdate =  self.chkAutoupdate.isChecked()
        iface         =  self.comboInterface.currentText()

        def _portable_key(ks_edit):
            qs = ks_edit.keySequence()
            if qs.isEmpty():
                return None
            return qs.toString(QKeySequence.PortableText)

        k_kill = _portable_key(self.keySeqKill)
        k_lag = _portable_key(self.keySeqLag)
        k_dupe = _portable_key(self.keySeqDupe)
        if not k_kill or not k_lag or not k_dupe:
            MsgType.WARN(
                self,
                'Keyboard shortcuts',
                'Each shortcut must have a key assigned.',
                Buttons.OK,
            )
            return
        if len({k_kill, k_lag, k_dupe}) < 3:
            MsgType.WARN(
                self,
                'Keyboard shortcuts',
                'Kill, Lag Switch, and Dupe shortcuts must all be different.',
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

        # Make sure that real-time killed devices are included
        # If its user's first time to apply remember option
        killed_from_json = get_settings('killed')
        killed_live = list(self.elmocut.killer.killed)
        killed_all = list(set(killed_from_json + killed_live)) * is_remember

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
            nicknames.nicknames_database,
            k_kill,
            k_lag,
            k_dupe,
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
        s = import_settings()
        self.currentSettings()
        
        self.elmocut.minimize = s['minimized']
        self.elmocut.remember = s['remember']
        self.elmocut.autoupdate = s['autoupdate']
        self.elmocut.scanner.device_count = s['count']
        self.elmocut.scanner.max_threads = s['threads']
        
        self.elmocut.scanner.iface = get_iface_by_name(s['iface'])
        self.elmocut.killer.iface = get_iface_by_name(s['iface'])
        
        self.elmocut.setStyleSheet(self.styleSheet())
        self.elmocut.about_window.setStyleSheet(self.styleSheet())
        for _dlg in (
            getattr(self.elmocut, 'lag_switch_dialog', None),
            getattr(self.elmocut, 'dupe_switch_dialog', None),
        ):
            if _dlg is not None:
                _dlg.setStyleSheet(self.elmocut.styleSheet())
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

    def currentSettings(self):
        s = import_settings()
        self.chkAutostart.setChecked(s['autostart'])
        self.chkMinimized.setChecked(s['minimized'])
        self.chkRemember.setChecked(s['remember'])
        self.chkAutoupdate.setEnabled(False)
        self.chkAutoupdate.setChecked(False)
        self.spinCount.setValue(s['count'])
        self.spinThreads.setValue(s['threads'])
        self.sliderCount.setValue(s['count'])
        self.sliderThreads.setValue(s['threads'])
        
        if not s['iface']:
            set_settings('iface', get_default_iface().name)
            s = import_settings()
        
        index = self.comboInterface.findText(s['iface'], Qt.MatchFixedString)
        self.comboInterface.setCurrentIndex(index * (index >= 0))

        self.keySeqKill.setKeySequence(keyseq_from_setting(s.get('key_kill'), Qt.Key_L))
        self.keySeqLag.setKeySequence(keyseq_from_setting(s.get('key_lag'), Qt.Key_M))
        self.keySeqDupe.setKeySequence(keyseq_from_setting(s.get('key_dupe'), Qt.Key_P))
        
        self.setStyleSheet(zubcut_dark_stylesheet())
    
    def checkUpdate(self):
        begin_updater_debug_session('settings.checkUpdate')
        updater_log('checkUpdate: entered')
        url = selected_update_url()
        if not url:
            MsgType.WARN(
                self,
                'Update URL Missing',
                (
                    'Set channel URL in constants.py:\n'
                    f'- UPDATE_DOWNLOAD_URL_{self._update_channel.upper()}'
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
                    f'Channel: {self._update_channel}'
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
        except RuntimeError:
            pass

    def _update_button_text(self):
        if self._update_channel == 'experimental':
            base = 'Install Latest Build (Experimental)'
        else:
            base = f'Install Latest Build ({APP_DISPLAY_NAME})'
        if self._update_available:
            base = f'New version available — {base}'
        if self._update_published_label:
            return f'{base} [{self._update_published_label}]'
        return base

    def _apply_update_button_style(self):
        if self._update_available:
            self.btnUpdate.setStyleSheet(
                'QPushButton { background-color: #1e8449; color: white; font-weight: bold; }'
            )
        else:
            self.btnUpdate.setStyleSheet('')
    
    def loadInterfaces(self):
        self.comboInterface.clear()
        self.comboInterface.addItems(
            [iface.name for iface in get_ifaces()]
        )