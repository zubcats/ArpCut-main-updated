"""
Filesystem paths for migrating settings from older ZubCut installs.

Folder/file names on disk are unchanged so existing user data is found automatically.
"""
from __future__ import annotations

from os import path

# Historical Documents subfolder and settings filename (pre-branding installs).
_WIN_DOCS_SUBDIR = 'elmocut'
_SETTINGS_JSON = 'elmocut.json'


def legacy_documents_path_windows(userprofile: str) -> str:
    return path.join(userprofile, 'Documents', _WIN_DOCS_SUBDIR)


def legacy_settings_path_windows(userprofile: str) -> str:
    return path.join(legacy_documents_path_windows(userprofile), _SETTINGS_JSON)


def legacy_documents_path_unix(home: str, *, darwin: bool) -> str:
    if darwin:
        return path.join(home, 'Library', 'Application Support', _WIN_DOCS_SUBDIR)
    return path.join(home, '.config', _WIN_DOCS_SUBDIR)


def legacy_settings_path_unix(home: str, *, darwin: bool) -> str:
    return path.join(legacy_documents_path_unix(home, darwin=darwin), _SETTINGS_JSON)
