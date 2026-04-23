"""
Qt plugin paths for PyInstaller bundles (stdlib only — no PyQt import).

PyInstaller 6 onedir puts almost everything under sys._MEIPASS (often .../_internal).
Qt must find platforms/qwindows.dll before QApplication is created.
"""

from __future__ import annotations

import os
import sys


def configure_qt_environment() -> None:
    if not getattr(sys, 'frozen', False):
        return
    roots: list[str] = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        roots.append(meipass)
    exe_dir = os.path.dirname(sys.executable)
    roots.append(os.path.join(exe_dir, '_internal'))
    roots.append(exe_dir)
    seen: set[str] = set()
    ordered: list[str] = []
    for r in roots:
        if r and r not in seen:
            seen.add(r)
            ordered.append(r)
    for root in ordered:
        for parts in (
            ('PyQt5', 'Qt5', 'plugins'),
            ('PyQt5', 'Qt', 'plugins'),
        ):
            plugins = os.path.join(root, *parts)
            platforms = os.path.join(plugins, 'platforms')
            qwin = os.path.join(platforms, 'qwindows.dll')
            if os.path.isfile(qwin):
                os.environ['QT_PLUGIN_PATH'] = plugins
                os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = platforms
                return
