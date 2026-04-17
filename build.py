#!/usr/bin/env python3
"""
Build script for ZubCut
Run: python build.py
"""

import os
import subprocess
import sys
import platform

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from src.constants import APP_BUNDLE_NAME

# All the imports PyInstaller is too dumb to find on its own
HIDDEN_IMPORTS = [
    'tools.updater_debug',
    'PyQt5',
    'PyQt5.QtWidgets',
    'PyQt5.QtCore', 
    'PyQt5.QtGui',
    'PyQt5.QtNetwork',
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
    
    # Base command (name must match constants.APP_BUNDLE_NAME for installer / autostart)
    # Use python -m PyInstaller so CI and venvs do not rely on a Scripts\pyinstaller.exe on PATH
    cmd = [sys.executable, '-m', 'PyInstaller', '--name', APP_BUNDLE_NAME]
    
    # Platform-specific options
    if system == 'Windows':
        # Onedir avoids one-file temp extraction (_MEI*) which often breaks python311.dll load
        # (AV, temp cleanup, or missing deps beside the DLL on some systems).
        cmd.extend(['--onedir', '--windowed'])
        cmd.extend(['--add-data', 'exe/manuf;manuf'])
        cmd.extend(['--add-data', 'exe/zubcut_icon.png;.'])
        cmd.extend(['--icon', 'exe/zubcut_icon.png'])
        cmd.extend(['--uac-admin'])  # Force admin elevation prompt
    elif system == 'Darwin':  # macOS
        cmd.extend(['--onedir', '--windowed'])
        cmd.extend(['--add-data', 'exe/manuf:manuf'])
        cmd.extend(['--add-data', 'exe/zubcut_icon.png:.'])
        cmd.extend(['--icon', 'exe/zubcut_icon.png'])
    else:  # Linux
        cmd.extend(['--onefile'])
        cmd.extend(['--add-data', 'exe/manuf:manuf'])
        cmd.extend(['--add-data', 'exe/zubcut_icon.png:.'])
    
    # Add hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(['--hidden-import', imp])
    
    # Collect all data for these packages
    for pkg in COLLECT_ALL:
        cmd.extend(['--collect-all', pkg])
    
    # Entry point
    cmd.append('src/zubcut.py')
    
    print(f"Building for {system}...")
    print(f"Command: {' '.join(cmd)}")
    print()
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print()
        print("Build complete!")
        if system == 'Windows':
            print(f"Output: dist/{APP_BUNDLE_NAME}/{APP_BUNDLE_NAME}.exe")
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
