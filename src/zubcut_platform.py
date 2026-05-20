"""
ZubCut platform gate — Windows is the supported production target.

macOS/Linux code paths remain in the tree for a possible future port but are not
exercised when ``ZUBCUT_WINDOWS_ONLY`` is true (default).
"""
from __future__ import annotations

import sys

# Set ZUBCUT_ALLOW_NON_WINDOWS=1 only for developer experiments on other OSes.
_WINDOWS_ONLY = not (
    str(__import__('os').environ.get('ZUBCUT_ALLOW_NON_WINDOWS', '')).strip()
    in ('1', 'true', 'yes')
)


def is_windows() -> bool:
    return sys.platform.startswith('win')


def windows_only_build() -> bool:
    return _WINDOWS_ONLY


def require_supported_platform() -> None:
    """Exit with a clear message if this build is Windows-only."""
    if not _WINDOWS_ONLY:
        return
    if is_windows():
        return
    name = 'ZubCut'
    try:
        from constants import APP_DISPLAY_NAME

        name = APP_DISPLAY_NAME
    except Exception:
        pass
    print(
        f'{name} is Windows-only in this release.\n'
        'Install on Windows 10/11 (64-bit) and run as Administrator.\n'
        'macOS support may return in a later version.',
        file=sys.stderr,
    )
    raise SystemExit(2)
