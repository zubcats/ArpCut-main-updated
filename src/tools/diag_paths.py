"""Shared Desktop folder for ZubCut diagnostic reports and helper scripts."""
from __future__ import annotations

import sys
from pathlib import Path

DIAGNOSTICS_FOLDER_NAME = 'ZubCut Diagnostics'


def desktop_dir() -> Path:
    """
    User Desktop — same folder PowerShell ``[Environment]::GetFolderPath('Desktop')`` uses.

    Prefer the Windows shell API so OneDrive Desktop redirection matches Quick check /
    other elevated PS1 reports. ``Path.home()/Desktop`` can point at a different folder.
    """
    if sys.platform.startswith('win'):
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY — physical Desktop (follows Known Folder redirect).
            hr = int(ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf))
            if hr == 0 and buf.value:
                p = Path(buf.value)
                if p.is_dir():
                    return p
        except Exception:
            pass
        try:
            import os

            user_profile = os.environ.get('USERPROFILE') or ''
            if user_profile:
                one = Path(user_profile) / 'OneDrive' / 'Desktop'
                if one.is_dir():
                    return one
                desk = Path(user_profile) / 'Desktop'
                if desk.is_dir():
                    return desk
        except Exception:
            pass

    home = Path.home()
    desk = home / 'Desktop'
    if desk.is_dir():
        return desk
    one = home / 'OneDrive' / 'Desktop'
    if one.is_dir():
        return one
    return home


def ensure_zubcut_diagnostics_dir() -> Path:
    """
    Return ``Desktop/ZubCut Diagnostics``, creating it only if missing.

    Finished diagnostic text reports go here. Runner scripts (``.ps1``) must
    **not** be written into this folder.
    """
    path = desktop_dir() / DIAGNOSTICS_FOLDER_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path
