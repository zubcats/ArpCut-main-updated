# CI copy of repo-root build.py. Copied to ./build.py before CI runs PyInstaller.
#!/usr/bin/env python3
"""
Build script for ZubCut
Run: python build.py
"""

import os
import shutil
import subprocess
import sys
import platform

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, 'src')
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# constants.py imports zubcut_legacy_migrate as a top-level module (same as src/zubcut.py).
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
from constants import APP_BUNDLE_NAME

# All the imports PyInstaller is too dumb to find on its own
HIDDEN_IMPORTS = [
    'zubcut_legacy_migrate',
    'ctypes.wintypes',
    'tools.license_offline',
    'tools.license_remote_signin',
    'gui.license_signin',
    'gui.traffic',
    'ui.ui_traffic',
    'tools.updater_debug',
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
    'cryptography',
    'cryptography.hazmat.primitives.asymmetric.ed25519',
    'cryptography.hazmat.backends.openssl',
    'cryptography.hazmat.backends.openssl.backend',
    'cryptography.hazmat.bindings._rust',
    'cryptography.hazmat.bindings.openssl',
    '_cffi_backend',
    'cffi',
]

COLLECT_ALL = [
    'manuf',
    'scapy',
    'qdarkstyle',
]


def _windows_pyinstaller_icon_path():
    """Prefer multi-size .ico so the taskbar / pinned shortcut shows a large-enough mark."""
    ico = os.path.join(_ROOT, 'exe', 'zubcut_shell.ico')
    png = os.path.join(_ROOT, 'exe', 'zubcut_icon.png')
    script = os.path.join(_ROOT, 'tools', 'build_windows_app_icon.py')
    if os.path.isfile(ico):
        return ico
    try:
        r = subprocess.run([sys.executable, script], cwd=_ROOT)
        if r.returncode == 0 and os.path.isfile(ico):
            return ico
    except OSError:
        pass
    print('Note: install Pillow (pip install pillow) to generate exe/zubcut_shell.ico for a richer taskbar icon.')
    return png


def _stage_windivert_dist_if_present() -> None:
    src_dir = os.path.join(_ROOT, 'installer', 'windivert')
    dll = os.path.join(src_dir, 'WinDivert.dll')
    sys_file = os.path.join(src_dir, 'WinDivert64.sys')
    if not (os.path.isfile(dll) and os.path.isfile(sys_file)):
        return
    dest_dir = os.path.join(_ROOT, 'dist', APP_BUNDLE_NAME, 'windivert')
    os.makedirs(dest_dir, exist_ok=True)
    for name in ('WinDivert.dll', 'WinDivert64.sys', 'WinDivert-LICENSE.txt'):
        src = os.path.join(src_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest_dir, name))
    print(f"Staged WinDivert: {dest_dir}")


def build():
    system = platform.system()

    # Base command (name must match constants.APP_BUNDLE_NAME for installer / autostart)
    cmd = [sys.executable, '-m', 'PyInstaller', '--name', APP_BUNDLE_NAME]
    cmd.extend(['--paths', os.path.join(_ROOT, 'src')])
    cmd.extend(['--collect-submodules', 'gui'])
    cmd.extend(['--additional-hooks-dir', os.path.join(_ROOT, 'packaging', 'pyinstaller-hooks')])

    if system == 'Windows':
        cmd.extend(['--onedir', '--windowed'])
        cmd.extend(['--add-data', 'exe/manuf;manuf'])
        cmd.extend(['--add-data', 'exe/zubcut_icon.png;.'])
        cmd.extend(['--add-data', 'exe/zubcut_shell.ico;.'])
        cmd.extend(['--add-data', 'tools/repair_clumsy_hotspot.ps1;tools'])
        cmd.extend(['--add-data', 'tools/Repair-Clumsy-Hotspot.cmd;tools'])
        _ico = _windows_pyinstaller_icon_path()
        cmd.extend(['--icon', os.path.relpath(_ico, _ROOT).replace('\\', '/')])
        cmd.extend(['--uac-admin'])
    elif system == 'Darwin':
        cmd.extend(['--onedir', '--windowed'])
        cmd.extend(['--add-data', 'exe/manuf:manuf'])
        cmd.extend(['--add-data', 'exe/zubcut_icon.png:.'])
        cmd.extend(['--icon', 'exe/zubcut_icon.png'])
    else:
        cmd.extend(['--onefile'])
        cmd.extend(['--add-data', 'exe/manuf:manuf'])
        cmd.extend(['--add-data', 'exe/zubcut_icon.png:.'])

    for imp in HIDDEN_IMPORTS:
        cmd.extend(['--hidden-import', imp])

    for pkg in COLLECT_ALL:
        cmd.extend(['--collect-all', pkg])

    cmd.append('src/zubcut.py')

    print(f"Building for {system}...")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=_ROOT)

    if result.returncode == 0:
        print()
        print("Build complete!")
        if system == 'Windows':
            _stage_windivert_dist_if_present()
            print(f"Output: dist/{APP_BUNDLE_NAME}/{APP_BUNDLE_NAME}.exe")
        elif system == 'Darwin':
            print(f"Output: dist/{APP_BUNDLE_NAME}.app")
            print(
                f"To create zip (name for CI): cd dist && zip -r {APP_BUNDLE_NAME}-macOS-arm64.zip {APP_BUNDLE_NAME}.app"
            )
            print("  (on Intel Mac use e.g. ZubCut-macOS-Intel.zip — see README / Build Release matrix)")
        else:
            print(f"Output: dist/{APP_BUNDLE_NAME}")
    else:
        print("Build failed!")
        sys.exit(1)


if __name__ == '__main__':
    build()
