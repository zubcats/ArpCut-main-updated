from os import path, makedirs, rename
import shutil
from json import dump, load, JSONDecodeError
import ctypes
import sys
try:
    import winreg  # Windows only
except Exception:
    winreg = None

from tools.utils import terminal
from constants import *



def is_admin():
    """
    Check if current user is Admin
    """
    if sys.platform.startswith('win'):
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    # On macOS/Linux, assume current user context (no UAC)
    return True

def npcap_exists():
    """
    Check for Npcap driver (Windows only)
    """
    if sys.platform.startswith('win'):
        return path.exists(NPCAP_PATH)
    # macOS/Linux uses libpcap (bundled); always True
    return True

def duplicate_zubcut():
    """Single-instance guard (reserved; not implemented)."""
    return False

def check_documents_dir():
    """
    Check if documents folder exists in order to store settings
    """
    makedirs(DOCUMENTS_PATH, exist_ok=True)
    if not path.exists(SETTINGS_PATH):
        export_settings()

def import_settings():
    """
    Get stored settings
    """
    check_documents_dir()
    return load(open(SETTINGS_PATH))

def export_settings(values=None):
    """
    Store current settings (or create new)
    """
    keys = SETTINGS_KEYS
    values = values if values else SETTINGS_VALS
    json = dict(zip(keys, values))
    dump(json, open(SETTINGS_PATH, 'w'))

def set_settings(key, value):
    """
    Update certain setting item
    """
    s = import_settings()
    s[key] = value
    export_settings(list(s.values()))

def get_settings(key):
    """
    Get certain setting item by key
    """
    return import_settings()[key]

def repair_settings():
    """
    Merge defaults when settings are missing keys or JSON is invalid.
    """
    original = dict(zip(SETTINGS_KEYS, SETTINGS_VALS))
    
    try:
        s = import_settings()
        for key in s:
            original[key] = s[key]
    except JSONDecodeError:
        pass
        
    export_settings(list(original.values()))

def migrate_settings_file():
    if path.exists(SETTINGS_PATH):
        return
    makedirs(DOCUMENTS_PATH, exist_ok=True)
    if path.exists(OLD_SETTINGS_PATH):
        try:
            rename(OLD_SETTINGS_PATH, SETTINGS_PATH)
            return
        except Exception as e:
            print(f'Migrating settings error: {e}')
    for legacy in LEGACY_SETTINGS_CANDIDATES:
        if legacy and path.exists(legacy):
            try:
                shutil.copy2(legacy, SETTINGS_PATH)
                return
            except Exception as e:
                print(f'Migrating settings from {legacy}: {e}')

def add_to_startup(exe_path):
    """
    Add ZubCut to autostart (Windows).
    """
    if sys.platform.startswith('win') and winreg:
        key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                HKEY_AUTOSTART_PATH,
                0,
                winreg.KEY_SET_VALUE
            )
        winreg.SetValueEx(
            key,
            AUTOSTART_REG_VALUE,
            0,
            winreg.REG_SZ, exe_path
        )

def remove_from_startup():
    """
    Remove ZubCut from autostart (Windows).
    """
    if sys.platform.startswith('win') and winreg:
        key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                HKEY_AUTOSTART_PATH,
                0,
                winreg.KEY_WRITE
            )
        try:
            winreg.DeleteValue(key, AUTOSTART_REG_VALUE)
        except FileNotFoundError:
            pass