#!/usr/bin/env python3
"""PyInstaller build for ZubCut Control Panel."""

from __future__ import annotations

import os
import platform
import subprocess
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from constants import CONTROL_PANEL_BUNDLE_NAME

HIDDEN_IMPORTS = [
    'ctypes.wintypes',
    'tools.qt_frozen_bootstrap',
    'gui.control_panel',
    'gui.crash_reports_panel',
    'tools.license_admin',
    'tools.license_cloud_sync',
    'tools.control_panel_crashes',
    'tools.updater_core',
    'tools.frameless_chrome',
    'tools.branding',
    'tools.logo_shell_crop',
    'assets',
    'zubcut_legacy_migrate',
    'PyQt5',
    'PyQt5.QtWidgets',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.sip',
    'qdarkstyle',
    'nacl',
    'nacl.signing',
    'nacl.bindings',
    '_cffi_backend',
    'certifi',
    'requests',
]

COLLECT_ALL = ['qdarkstyle', 'nacl', 'cffi']
COLLECT_PYQT5 = ['Windows', 'Darwin']


def build() -> int:
    system = platform.system()
    cmd = [sys.executable, '-m', 'PyInstaller', '--name', CONTROL_PANEL_BUNDLE_NAME]
    cmd.extend(['--paths', os.path.join(_ROOT, 'src')])
    cmd.extend(['--collect-submodules', 'gui'])
    _hooks = os.path.join(_ROOT, 'packaging', 'pyinstaller-hooks')
    cmd.extend(['--additional-hooks-dir', _hooks])
    cmd.extend(['--runtime-hook', os.path.join(_hooks, 'rthook_qt_control_panel.py')])
    cmd.append('--noupx')
    if system in COLLECT_PYQT5:
        cmd.extend(['--collect-all', 'PyQt5'])
    if system == 'Windows':
        cmd.extend(['--onedir', '--windowed'])
        cmd.extend(['--add-data', 'exe/zubcut_icon.png;.'])
        cmd.extend(['--icon', 'exe/zubcut_icon.png'])
    elif system == 'Darwin':
        cmd.extend(['--onedir', '--windowed'])
        cmd.extend(['--add-data', 'exe/zubcut_icon.png:.'])
        cmd.extend(['--icon', 'exe/zubcut_icon.png'])
    else:
        cmd.extend(['--onefile'])
        cmd.extend(['--add-data', 'exe/zubcut_icon.png;.'])
    for imp in HIDDEN_IMPORTS:
        cmd.extend(['--hidden-import', imp])
    for pkg in COLLECT_ALL:
        cmd.extend(['--collect-all', pkg])
    cmd.extend(['--collect-data', 'certifi'])
    cmd.append('src/zubcut_control_panel.py')
    print(f'Building {CONTROL_PANEL_BUNDLE_NAME} for {system}...')
    result = subprocess.run(cmd, cwd=_ROOT)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(build())
