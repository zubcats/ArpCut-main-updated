#!/usr/bin/env python3
"""
Build script for ZubCut License Manager
Run: python build_license_manager.py
"""

import os
import platform
import subprocess
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))

APP_NAME = 'ZubCutLicenseManager'

HIDDEN_IMPORTS = [
    'gui.license_manager',
    'tools.license_admin',
    'PyQt5',
    'PyQt5.QtWidgets',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.sip',
    'qdarkstyle',
    'nacl',
    'nacl.signing',
]

COLLECT_ALL = [
    'qdarkstyle',
    'nacl',
]


def build():
    system = platform.system()
    cmd = [sys.executable, '-m', 'PyInstaller', '--name', APP_NAME]
    cmd.extend(['--paths', os.path.join(_ROOT, 'src')])
    cmd.extend(['--collect-submodules', 'gui'])
    cmd.extend(['--additional-hooks-dir', os.path.join(_ROOT, 'packaging', 'pyinstaller-hooks')])

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
        cmd.extend(['--add-data', 'exe/zubcut_icon.png:.'])

    for imp in HIDDEN_IMPORTS:
        cmd.extend(['--hidden-import', imp])
    for pkg in COLLECT_ALL:
        cmd.extend(['--collect-all', pkg])

    cmd.append('src/zubcut_license_manager.py')

    print(f'Building {APP_NAME} for {system}...')
    print(f"Command: {' '.join(cmd)}")
    print()
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print('Build failed!')
        sys.exit(1)
    print('Build complete!')
    if system == 'Windows':
        print(f'Output: dist/{APP_NAME}/{APP_NAME}.exe')
    elif system == 'Darwin':
        print(f'Output: dist/{APP_NAME}.app')
    else:
        print(f'Output: dist/{APP_NAME}')


if __name__ == '__main__':
    build()

