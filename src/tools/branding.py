"""
Load the ZubCut logo as a multi-resolution QIcon (title bar, taskbar, tray, shortcuts).
A single PNG loaded with QIcon(path) often appears tiny on Windows because no size ladder is registered.
"""
import os
import sys

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QPainter, QPixmap

from tools.logo_shell_crop import shell_content_fraction_for_target_px

_ICON_FILE = 'zubcut_icon.png'
# Windows: same multi-res file PyInstaller uses for the .exe; better DWM / taskbar preview than PNG QIcon.
_SHELL_ICO_FILE = 'zubcut_shell.ico'
# HWND class icons only (taskbar + Aero Peek title-bar chip via WM_SETICON). Custom caption / tray / toolbar
# use full QIcon pixmaps. Lower fraction = smaller glyph inside the shell square so circular masks do not clip.
SHELL_HWND_ICON_INNER_FRACTION = 0.72

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


def load_shell_window_icon():
    """
    Icon for setWindowIcon / tray on Windows: native QIcon from zubcut_shell.ico (same as --icon).
    A custom QIconEngine often fights Explorer: taskbar + hover chip then reuse tiny pixmaps.
    """
    if sys.platform != 'win32':
        return load_shell_application_qicon()

    ico = resolve_zubcut_shell_ico_path()
    if ico:
        icon = QIcon(ico)
        if not qicon_is_empty(icon):
            return icon

    return load_shell_application_qicon()


def qicon_is_empty(icon):
    if icon.isNull():
        return True
    if icon.availableSizes():
        return False
    # QIcon loaded from .ico may not populate availableSizes() until first pixmap().
    return icon.pixmap(32, 32).isNull()


def _windows_native_icon_source_path() -> str | None:
    """Frozen builds: same PE as the desktop shortcut (best match). Dev: zubcut_shell.ico."""
    if getattr(sys, 'frozen', False) and getattr(sys, 'executable', None):
        exe = os.path.abspath(sys.executable)
        if os.path.isfile(exe):
            return exe
    ico = resolve_zubcut_shell_ico_path()
    if ico and os.path.isfile(ico):
        return os.path.abspath(ico)
    return None


def _effective_window_dpi(window, hwnd: int, user32) -> int:
    """
    Qt frameless windows often report 96 from GetDpiForWindow while the screen is 125%/150%.
    Blend Win32 DPI with QScreen.devicePixelRatio so LoadImage requests match the real taskbar.
    """
    dpi_win = 0
    try:
        d = int(user32.GetDpiForWindow(hwnd))
        if d > 0:
            dpi_win = d
    except AttributeError:
        pass
    dpi_qt = 0
    try:
        wh = window.windowHandle()
        if wh is not None and wh.screen() is not None:
            dpi_qt = int(round(96.0 * float(wh.screen().devicePixelRatio())))
    except Exception:
        pass
    return max(dpi_win, dpi_qt, 96)


def _hwnd_hicon_from_ico_padded(ico_abs: str, canvas_px: int) -> int:
    """Build HICON with the mark scaled to a fraction of the shell square (smaller glyph in taskbar/peek)."""
    if canvas_px < 4:
        return 0
    try:
        from PyQt5.QtWinExtras import QtWin
    except ImportError:
        return 0
    ic = QIcon(ico_abs)
    if ic.isNull():
        return 0
    pm = QPixmap(canvas_px, canvas_px)
    pm.fill(Qt.transparent)
    inner_side = max(1, int(round(canvas_px * SHELL_HWND_ICON_INNER_FRACTION)))
    inner = ic.pixmap(inner_side, inner_side)
    if inner.isNull():
        return 0
    painter = QPainter(pm)
    painter.drawPixmap((canvas_px - inner.width()) // 2, (canvas_px - inner.height()) // 2, inner)
    painter.end()
    h = QtWin.toHICON(pm)
    return int(h) if h else 0


def _win_hwnd_icon_pixel_sizes(window, hwnd: int, user32) -> tuple[int, int]:
    """(small_cx, large_cx) for LoadImage — scales with effective DPI."""
    dpi = _effective_window_dpi(window, hwnd, user32)
    SM_CXSMICON = 49
    SM_CXICON = 11
    try:
        sm = int(user32.GetSystemMetricsForDpi(SM_CXSMICON, dpi))
        lg = int(user32.GetSystemMetricsForDpi(SM_CXICON, dpi))
    except AttributeError:
        sm = max(16, int(round(16 * dpi / 96.0)))
        lg = max(32, int(round(32 * dpi / 96.0)))
    return max(16, sm), max(32, lg)


def install_windows_native_window_icons(window) -> bool:
    """
    Push Win32 small/large icons into the HWND (WM_SETICON + class icons).
    Prefer LoadImage from zubcut_shell.ico at DPI-aware sizes (sharp taskbar on 125%/150%).
    Fallback: ExtractIconEx from the .exe / path.
    """
    if sys.platform != 'win32':
        return False
    try:
        hwnd = int(window.winId())
    except (AttributeError, TypeError, ValueError):
        return False
    if hwnd == 0:
        return False

    import ctypes

    src = _windows_native_icon_source_path()
    if not src:
        return False

    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
    WM_SETICON = 0x0080
    ICON_SMALL = 0
    ICON_BIG = 1
    GCL_HICON = -14
    GCL_HICONSM = -34
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010

    sm_px, lg_px = _win_hwnd_icon_pixel_sizes(window, hwnd, user32)
    h_sm = 0
    h_lg = 0

    ico = resolve_zubcut_shell_ico_path()
    if ico and os.path.isfile(ico):
        ico_abs = os.path.abspath(ico)
        h_sm = _hwnd_hicon_from_ico_padded(ico_abs, sm_px)
        h_lg = _hwnd_hicon_from_ico_padded(ico_abs, lg_px)
        if not h_sm:
            h_sm = int(user32.LoadImageW(None, ico_abs, IMAGE_ICON, sm_px, sm_px, LR_LOADFROMFILE) or 0)
        if not h_lg:
            h_lg = int(user32.LoadImageW(None, ico_abs, IMAGE_ICON, lg_px, lg_px, LR_LOADFROMFILE) or 0)

    if not h_sm or not h_lg:
        large = ctypes.c_void_p()
        small = ctypes.c_void_p()
        n = shell32.ExtractIconExW(src, 0, ctypes.byref(large), ctypes.byref(small), 1)
        h_lg = h_lg or int(large.value or 0)
        h_sm = h_sm or int(small.value or 0)

    if not h_sm or not h_lg:
        ico = resolve_zubcut_shell_ico_path()
        if ico and os.path.isfile(ico):
            ico_abs = os.path.abspath(ico)
            h_sm = h_sm or int(
                user32.LoadImageW(None, ico_abs, IMAGE_ICON, sm_px, sm_px, LR_LOADFROMFILE) or 0
            )
            h_lg = h_lg or int(
                user32.LoadImageW(None, ico_abs, IMAGE_ICON, lg_px, lg_px, LR_LOADFROMFILE) or 0
            )

    if not h_lg and not h_sm:
        return False

    try:
        set_cls = user32.SetClassLongPtrW
    except AttributeError:
        set_cls = user32.SetClassLongW

    if h_sm:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_sm)
    if h_lg:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_lg)
    if h_lg:
        set_cls(hwnd, GCL_HICON, h_lg)
    if h_sm:
        set_cls(hwnd, GCL_HICONSM, h_sm)

    return True
