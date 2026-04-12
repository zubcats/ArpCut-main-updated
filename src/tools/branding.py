"""
Load the ZubCut logo as a multi-resolution QIcon (title bar, taskbar, tray, shortcuts).
A single PNG loaded with QIcon(path) often appears tiny on Windows because no size ladder is registered.
"""
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPixmap

_ICON_FILE = 'zubcut_icon.png'

# Sizes commonly requested by Windows shells and Qt (device-independent pixels).
_STANDARD_SIZES = (16, 20, 24, 32, 40, 48, 64, 72, 96, 128, 256)


def zubcut_png_candidates():
    """Ordered search paths: frozen bundle, dev tree."""
    here = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.dirname(here)
    root = os.path.dirname(src_dir)
    c = [
        os.path.join(root, 'exe', _ICON_FILE),
        os.path.normpath(os.path.join(src_dir, '..', 'exe', _ICON_FILE)),
    ]
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            c.insert(0, os.path.join(meipass, _ICON_FILE))
        c.insert(0, os.path.join(os.path.dirname(sys.executable), _ICON_FILE))
    seen = set()
    out = []
    for p in c:
        rp = os.path.normpath(p)
        if rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out


def resolve_zubcut_png_path():
    for p in zubcut_png_candidates():
        if os.path.isfile(p):
            return p
    return None


def qicon_from_png_path(path):
    """Build QIcon with explicit sizes so the OS picks a crisp pixmap everywhere."""
    pm = QPixmap(path)
    if pm.isNull():
        return QIcon()
    icon = QIcon()
    for s in _STANDARD_SIZES:
        icon.addPixmap(
            pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation),
            QIcon.Normal,
            QIcon.Off,
        )
    icon.addPixmap(pm, QIcon.Normal, QIcon.Off)
    return icon


def load_application_qicon():
    path = resolve_zubcut_png_path()
    if not path:
        return QIcon()
    return qicon_from_png_path(path)


def qicon_is_empty(icon):
    return icon.isNull() or not icon.availableSizes()
