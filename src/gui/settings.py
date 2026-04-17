from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtCore import Qt
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from tools.utils_gui import import_settings, export_settings, get_settings, \
                      is_admin, add_to_startup, remove_from_startup, set_settings, \
                      zubcut_dark_stylesheet, sync_translucent_chrome, register_window_surface_effects
from tools.frameless_chrome import FramelessResizableMixin, setup_frameless_main_window
from tools.qtools import MsgType, Buttons
from tools.utils import goto, get_ifaces, get_default_iface, get_iface_by_name, terminal

from ui.ui_settings import Ui_MainWindow

from networking.nicknames import Nicknames

from tools.keybinds import keyseq_from_setting

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
        self._refresh_update_availability()
        self.btnUpdate.setText(self._update_button_text())
        # Keep background auto-update disabled; manual update button is available.
        self.chkAutoupdate.setEnabled(False)
        self.chkAutoupdate.setChecked(False)

        setup_frameless_main_window(self, self.windowTitle(), self.icon, maximizable=False)
        register_window_surface_effects(self)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_update_availability()
        self.btnUpdate.setText(self._update_button_text())
        self._apply_update_button_style()

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
        if self._update_channel == 'stable':
            url = (UPDATE_DOWNLOAD_URL_STABLE or '').strip()
        else:
            url = (UPDATE_DOWNLOAD_URL_EXPERIMENTAL or '').strip()
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

        confirm = MsgType.WARN(
            self,
            'Install Latest Build',
            (
                f'This will install the latest {self._channel_label()} build.\n'
                'The app will download the package, close, and run the installer.\n'
                'Continue?'
            ),
            Buttons.YES | Buttons.NO,
        )
        if confirm == Buttons.NO:
            return

        self.btnUpdate.setEnabled(False)
        self.btnUpdate.setText('Downloading...')
        QApplication.processEvents()
        tmp_path = None
        try:
            # Pick filename from URL path, fallback to app setup name.
            url_path = urlparse(url).path or ''
            fname = os.path.basename(url_path) or f'{APP_BUNDLE_NAME}-Setup-latest.exe'
            if not fname.lower().endswith('.exe'):
                fname = f'{APP_BUNDLE_NAME}-Setup-latest.exe'
            stem, ext = os.path.splitext(fname)
            tmp_fname = f'{stem}-{int(time.time())}{ext or ".exe"}'
            tmp_path = os.path.join(tempfile.gettempdir(), tmp_fname)
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

            # Avoid stale edge-cache responses by adding a cache-buster query and no-cache headers.
            parsed = urlparse(url)
            query_items = parse_qsl(parsed.query, keep_blank_values=True)
            query_items.append(('cb', str(int(time.time()))))
            download_url = urlunparse(parsed._replace(query=urlencode(query_items)))
            req = urllib.request.Request(
                download_url,
                headers={
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache',
                    'User-Agent': f'{APP_BUNDLE_NAME}-updater',
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_path, 'wb') as fp:
                shutil.copyfileobj(resp, fp)
            if not os.path.exists(tmp_path):
                raise RuntimeError('Downloaded file missing.')
            if os.path.getsize(tmp_path) < 1024:
                raise RuntimeError('Downloaded file is too small to be a valid installer.')
            with open(tmp_path, 'rb') as fp:
                if fp.read(2) != b'MZ':
                    raise RuntimeError('Downloaded file is not a Windows installer executable.')

            self.btnUpdate.setText('Launching installer...')
            QApplication.processEvents()

            # Launch installer silently, then exit this app to avoid file lock conflicts.
            install_log = os.path.join(tempfile.gettempdir(), f'{APP_BUNDLE_NAME.lower()}-update-install.log')
            installer_args = [tmp_path, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', f'/LOG={install_log}']
            subprocess.Popen(installer_args, close_fds=True)
            self.elmocut.quit_all()
        except Exception as e:
            MsgType.ERROR(
                self,
                'Update Failed',
                f'Could not download/install update.\n{e}',
                Buttons.OK,
            )
        finally:
            if self.isVisible():
                self.btnUpdate.setEnabled(True)
                self.btnUpdate.setText(self._update_button_text())
                self._apply_update_button_style()

    def _channel_label(self):
        return 'experimental' if self._update_channel == 'experimental' else APP_DISPLAY_NAME

    def _selected_update_url(self):
        if self._update_channel == 'stable':
            return (UPDATE_DOWNLOAD_URL_STABLE or '').strip()
        return (UPDATE_DOWNLOAD_URL_EXPERIMENTAL or '').strip()

    @staticmethod
    def _parse_build_time_iso(raw):
        if not raw or not str(raw).strip():
            return None
        s = str(raw).strip()
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    def _refresh_update_availability(self):
        """Fetch remote installer time; compare to embedded build time when CI set it."""
        url = self._selected_update_url()
        self._update_published_label = ''
        self._update_available = False
        if not url:
            return
        try:
            req = urllib.request.Request(
                url,
                method='HEAD',
                headers={'User-Agent': f'{APP_BUNDLE_NAME}-update-check'},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                last_modified = resp.headers.get('Last-Modified', '').strip()
            if not last_modified:
                return
            remote_dt = parsedate_to_datetime(last_modified)
            if remote_dt is None:
                return
            if remote_dt.tzinfo is None:
                remote_dt = remote_dt.replace(tzinfo=timezone.utc)
            dt_local = remote_dt.astimezone()
            self._update_published_label = dt_local.strftime('%b %d, %Y %I:%M %p')
            build_raw = APP_BUILD_TIME_ISO
            local_dt = self._parse_build_time_iso(build_raw)
            if local_dt is None:
                return
            if local_dt.tzinfo is None:
                local_dt = local_dt.replace(tzinfo=timezone.utc)
            remote_utc = remote_dt.astimezone(timezone.utc)
            local_utc = local_dt.astimezone(timezone.utc)
            self._update_available = remote_utc > local_utc
        except Exception:
            self._update_published_label = ''
            self._update_available = False

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