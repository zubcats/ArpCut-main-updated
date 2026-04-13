from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtCore import Qt
import os
import sys

from tools.utils_gui import import_settings, export_settings, get_settings, \
                      is_admin, add_to_startup, remove_from_startup, set_settings, \
                      zubcut_dark_stylesheet, sync_translucent_chrome
from tools.qtools import MsgType, Buttons
from tools.utils import goto, get_ifaces, get_default_iface, get_iface_by_name, terminal

from ui.ui_settings import Ui_MainWindow

from networking.nicknames import Nicknames

from tools.keybinds import keyseq_from_setting

from constants import *

class Settings(QMainWindow, Ui_MainWindow):
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
        # Update button disabled for fork
        self.btnUpdate.setEnabled(False)
        self.btnUpdate.setText("Updates Disabled")
        self.chkAutoupdate.setEnabled(False)
        self.chkAutoupdate.setChecked(False)
    
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
        sync_translucent_chrome(
            [
                self.elmocut,
                self.elmocut.about_window,
                self,
                self.elmocut.device_window,
                self.elmocut.traffic_window,
            ],
        )
        self.elmocut.refresh_keyboard_shortcuts_from_settings()

    def currentSettings(self):
        s = import_settings()
        self.chkAutostart.setChecked(s['autostart'])
        self.chkMinimized.setChecked(s['minimized'])
        self.chkRemember.setChecked(s['remember'])
        self.chkAutoupdate.setChecked(s['autoupdate'])
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
        # Update checking disabled for this fork
        MsgType.INFO(
            self,
            'Updates Disabled',
            'Update checking is disabled for this build.'
        )
    
    def loadInterfaces(self):
        self.comboInterface.clear()
        self.comboInterface.addItems(
            [iface.name for iface in get_ifaces()]
        )