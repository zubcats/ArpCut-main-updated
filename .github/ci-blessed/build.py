# CI copy of repo-root build.py. Copied to ./build.py before CI runs PyInstaller.
#!/usr/bin/env python3
"""
Build script for ArpCut
Run: python build.py
"""

import os
import subprocess
import sys
import platform

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, 'src'))
from src.constants import APP_BUNDLE_NAME

HIDDEN_IMPORTS = [
    'PyQt5',
    'PyQt5.QtWidgets',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.sip',
    'qdarkstyle',
    'scapy',
    'scapy.all',
    'scapy.layers.all',
    'manuf',
    'pyperclip',
    'requests',
    'six',
]

COLLECT_ALL = [
    'manuf',
    'scapy',
    'qdarkstyle',
]


def build():
    system = platform.system()

    cmd = [sys.executable, '-m', 'PyInstaller', '--name', APP_BUNDLE_NAME]

    if system == 'Windows':
        cmd.extend(['--onefile', '--windowed'])
        cmd.extend(['--add-data', 'exe/manuf;manuf'])
        cmd.extend(['--icon', 'exe/icon.ico'])
        cmd.extend(['--uac-admin'])
    elif system == 'Darwin':
        cmd.extend(['--onedir', '--windowed'])
        cmd.extend(['--add-data', 'exe/manuf:manuf'])
        cmd.extend(['--icon', 'exe/icon.ico'])
    else:
        cmd.extend(['--onefile'])
        cmd.extend(['--add-data', 'exe/manuf:manuf'])

    for imp in HIDDEN_IMPORTS:
        cmd.extend(['--hidden-import', imp])

    for pkg in COLLECT_ALL:
        cmd.extend(['--collect-all', pkg])

    cmd.append('src/elmocut.py')

    print(f"Building for {system}...")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print()
        print("Build complete!")
        if system == 'Windows':
            print(f"Output: dist/{APP_BUNDLE_NAME}.exe")
        elif system == 'Darwin':
            print(f"Output: dist/{APP_BUNDLE_NAME}.app")
            print(f"To create zip: cd dist && zip -r {APP_BUNDLE_NAME}-macOS.zip {APP_BUNDLE_NAME}.app")
        else:
            print(f"Output: dist/{APP_BUNDLE_NAME}")
    else:
        print("Build failed!")
        sys.exit(1)


if __name__ == '__main__':
    build()
