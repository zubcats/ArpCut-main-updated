"""
Load the ZubCut logo as a multi-resolution QIcon (title bar, taskbar, tray, shortcuts).
A single PNG loaded with QIcon(path) often appears tiny on Windows because no size ladder is registered.
"""
import os
import sys

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QIconEngine, QPainter, QPixmap

from tools.logo_shell_crop import shell_content_fraction_for_target_px

_ICON_FILE = 'zubcut_icon.png'
# Windows: same multi-res file PyInstaller uses for the .exe; better DWM / taskbar preview than PNG QIcon.
_SHELL_ICO_FILE = 'zubcut_shell.ico'

# Sizes commonly requested by Windows shells and Qt (device-independent pixels).
# Extra mids (22–44) help Windows 10/11 taskbar pick a sharp pixmap at 125%/150% DPI.
_STANDARD_SIZES = (
    16,
    20,
    22,
    24,
    28,
    30,
    32,
    36,
    40,
    44,
    48,
    56,
    64,
    72,
    96,
    128,
    256,
)

# zubcut_icon.png has a lot of empty margin; crop the center before building QIcons.
# Include more of the source art so the gold outline is not cropped out of the toolbar About button.
LOGO_UI_CONTENT_FRACTION = 0.64
# Legacy single fraction (shell icons now use shell_content_fraction_for_target_px per size).
LOGO_SHELL_CONTENT_FRACTION = 0.34  # legacy; shell uses logo_shell_crop tiers


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


def zubcut_shell_ico_candidates():
    """Search paths for zubcut_shell.ico (mirrors zubcut_png_candidates)."""
    here = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.dirname(here)
    root = os.path.dirname(src_dir)
    c = [
        os.path.join(root, 'exe', _SHELL_ICO_FILE),
        os.path.normpath(os.path.join(src_dir, '..', 'exe', _SHELL_ICO_FILE)),
    ]
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            c.insert(0, os.path.join(meipass, _SHELL_ICO_FILE))
        c.insert(0, os.path.join(os.path.dirname(sys.executable), _SHELL_ICO_FILE))
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


def resolve_zubcut_shell_ico_path():
    for p in zubcut_shell_ico_candidates():
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


def qicon_from_png_path_shell(path: str) -> QIcon:
    """QIcon ladder for taskbar / tray / OS chrome: tiered crop by requested pixmap size."""
    pm_orig = QPixmap(path)
    if pm_orig.isNull():
        return QIcon()
    icon = QIcon()
    for s in _STANDARD_SIZES:
        frac = shell_content_fraction_for_target_px(s)
        pm = crop_logo_content(pm_orig, frac)
        icon.addPixmap(
            pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation),
            QIcon.Normal,
            QIcon.Off,
        )
    return icon


def load_shell_application_qicon():
    path = resolve_zubcut_png_path()
    if not path:
        return QIcon()
    return qicon_from_png_path_shell(path)


class _ShellIconLetterboxEngine(QIconEngine):
    """
    Windows taskbar hover thumbnail asks Qt for a wide, short QSize. QIcon then returns a
    small square pixmap; the shell stretches it to the title strip → warped Z. We always
    return a pixmap of the *requested* size with the mark letterboxed (same fix for paint()).
    """

    def __init__(self, source: QIcon):
        super().__init__()
        self._source = source

    def clone(self):
        return _ShellIconLetterboxEngine(QIcon(self._source))

    def pixmap(self, size, mode, state):
        if size.isEmpty():
            return QPixmap()
        side = max(size.width(), size.height())
        inner = self._source.pixmap(QSize(side, side), mode, state)
        if inner.isNull():
            return inner
        if size.width() == size.height():
            return inner.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        out = QPixmap(size)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            scaled = inner.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (size.width() - scaled.width()) // 2
            y = (size.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        finally:
            painter.end()
        return out

    def scaledPixmap(self, size, mode, state, scale):
        # HiDPI icon path; size is typically device pixels — letterbox like pixmap().
        return self.pixmap(size, mode, state)

    def paint(self, painter, rect, mode, state):
        if rect.isEmpty():
            return
        side = max(rect.width(), rect.height())
        inner = self._source.pixmap(QSize(side, side), mode, state)
        if inner.isNull():
            return
        scaled = inner.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = rect.x() + (rect.width() - scaled.width()) // 2
        y = rect.y() + (rect.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


def _wrap_shell_icon_for_windows(base: QIcon) -> QIcon:
    if base.isNull():
        return base
    return QIcon(_ShellIconLetterboxEngine(base))


def load_shell_window_icon():
    """
    Icon for setWindowIcon / tray on Windows: prefer multi-res .ico on disk.
    Letterbox engine fixes DWM stretching when thumbnail chrome requests a wide pixmap size.
    """
    if sys.platform != 'win32':
        return load_shell_application_qicon()

    ico = resolve_zubcut_shell_ico_path()
    if ico:
        icon = QIcon(ico)
        if not qicon_is_empty(icon):
            return _wrap_shell_icon_for_windows(icon)

    return _wrap_shell_icon_for_windows(load_shell_application_qicon())


def qicon_is_empty(icon):
    if icon.isNull():
        return True
    if icon.availableSizes():
        return False
    # QIcon loaded from .ico may not populate availableSizes() until first pixmap().
    return icon.pixmap(32, 32).isNull()


def install_windows_native_window_icons(window) -> None:
    """
    Force HWND large/small icons from zubcut_shell.ico via WM_SETICON + class icons.
    Live taskbar thumbnails often read Win32 icons directly; Qt-only setWindowIcon can leave
    DWM drawing a different/low-res pixmap than the embedded PE icon.
    """
    if sys.platform != 'win32':
        return
    path = resolve_zubcut_shell_ico_path()
    if not path:
        return
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return
    try:
        hwnd = int(window.winId())
    except (AttributeError, TypeError, ValueError):
        return
    import ctypes

    user32 = ctypes.windll.user32
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010
    WM_SETICON = 0x0080
    ICON_SMALL = 0
    ICON_BIG = 1
    GCL_HICON = -14
    GCL_HICONSM = -34

    def _load(cx: int, cy: int) -> int:
        h = user32.LoadImageW(None, path, IMAGE_ICON, cx, cy, LR_LOADFROMFILE)
        return int(h) if h else 0

    h16 = _load(16, 16)
    h32 = _load(32, 32)
    if not h16 and not h32:
        return
    if h16:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h16)
    if h32:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h32)
    try:
        set_cls = user32.SetClassLongPtrW
    except AttributeError:
        set_cls = user32.SetClassLongW
    if h32:
        set_cls(hwnd, GCL_HICON, h32)
    if h16:
        set_cls(hwnd, GCL_HICONSM, h16)
