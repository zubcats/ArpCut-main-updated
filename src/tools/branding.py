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

# zubcut_icon.png has a lot of empty margin; crop the center before building QIcons so
# toolbar / tray / title bar show a larger mark. About dialog uses the uncropped file.
LOGO_UI_CONTENT_FRACTION = 0.56


def crop_logo_content(pm: QPixmap, fraction: float = LOGO_UI_CONTENT_FRACTION) -> QPixmap:
    """Keep a centered square window of the image; fraction is side length vs min(w,h)."""
    if pm.isNull() or fraction >= 1.0:
        return QPixmap(pm)
    w, h = pm.width(), pm.height()
    if w < 2 or h < 2:
        return QPixmap(pm)
    side = max(1, int(min(w, h) * fraction))
    x = (w - side) // 2
    y = (h - side) // 2
    return pm.copy(x, y, side, side)


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


def qicon_from_png_path(path, content_fraction=LOGO_UI_CONTENT_FRACTION):
    """Build QIcon with explicit sizes so the OS picks a crisp pixmap everywhere."""
    pm = QPixmap(path)
    if pm.isNull():
        return QIcon()
    pm = crop_logo_content(pm, content_fraction)
    icon = QIcon()
    for s in _STANDARD_SIZES:
        icon.addPixmap(
            pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation),
            QIcon.Normal,
            QIcon.Off,
        )
    icon.addPixmap(pm, QIcon.Normal, QIcon.Off)
    return icon


def load_application_qicon(content_fraction=LOGO_UI_CONTENT_FRACTION):
    path = resolve_zubcut_png_path()
    if not path:
        return QIcon()
    return qicon_from_png_path(path, content_fraction)


def qicon_is_empty(icon):
    return icon.isNull() or not icon.availableSizes()
