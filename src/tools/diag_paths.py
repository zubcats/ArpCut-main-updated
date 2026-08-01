"""Shared Desktop folder for ZubCut diagnostic reports and helper scripts."""
from __future__ import annotations

from pathlib import Path

DIAGNOSTICS_FOLDER_NAME = 'ZubCut Diagnostics'


def desktop_dir() -> Path:
    """User Desktop (OneDrive Desktop fallback, then home)."""
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
