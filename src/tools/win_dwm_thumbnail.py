"""
Windows DWM taskbar hover / peek previews.

Without handling WM_DWMSENDICONICTHUMBNAIL and WM_DWMSENDICONICLIVEPREVIEWBITMAP, the shell
often composites a scaled snapshot of the frameless window (tiny title strip → thin/wrong Z).

We register as an iconic bitmap provider and supply charcoal + centered logo bitmaps at the
sizes DWM requests (matches CustomTitleBar chrome).
"""
from __future__ import annotations

import ctypes
import sys
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from PyQt5.QtWidgets import QWidget

# https://learn.microsoft.com/en-us/windows/win32/dwm/wm-dwmsendiconicthumbnail
WM_DWMSENDICONICTHUMBNAIL = 0x0323
WM_DWMSENDICONICLIVEPREVIEWBITMAP = 0x0326

DWMWA_FORCE_ICONIC_REPRESENTATION = 7
DWMWA_HAS_ICONIC_BITMAP = 10
DWM_SIT_DISPLAYFRAME = 0x00000001

_logo_icon_cache = None


def _is_windows_generic_msg(event_type: object) -> bool:
    if isinstance(event_type, bytes):
        return b"windows_generic_MSG" in event_type or b"windows_dispatcher" in event_type
    s = str(event_type)
    return "windows_generic_MSG" in s or "windows_dispatcher" in s


def _msg_from_native(message: object) -> Optional[ctypes.wintypes.MSG]:
    try:
        addr = int(message)
    except (TypeError, ValueError):
        return None
    if addr == 0:
        return None
    try:
        return ctypes.wintypes.MSG.from_address(addr)
    except (ValueError, ctypes.ArgumentError):
        return None


def _shell_qicon():
    global _logo_icon_cache
    if _logo_icon_cache is not None:
        return _logo_icon_cache
    from PyQt5.QtGui import QIcon

    from tools.branding import resolve_zubcut_shell_ico_path

    p = resolve_zubcut_shell_ico_path()
    if p:
        _logo_icon_cache = QIcon(p)
    else:
        _logo_icon_cache = QIcon()
    return _logo_icon_cache


def _compose_branded_bitmap(max_w: int, max_h: int):
    """Charcoal panel + centered shell ICO (same framing family as the title bar)."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QColor, QPainter, QPixmap

    w = max(1, min(max_w, 4096))
    h = max(1, min(max_h, 4096))
    pm = QPixmap(w, h)
    pm.fill(QColor(0x2B, 0x2B, 0x2B))
    ico = _shell_qicon()
    if ico.isNull():
        return pm
    side = min(w, h)
    lg = ico.pixmap(side, side)
    if lg.isNull():
        return pm
    p = QPainter(pm)
    p.drawPixmap((w - lg.width()) // 2, (h - lg.height()) // 2, lg)
    p.end()
    return pm


def dwm_apply_iconic_bitmap_attributes(hwnd: int) -> None:
    """Tell DWM we supply iconic thumbnails/peek bitmaps (required before DwmSetIconic* works)."""
    if sys.platform != 'win32' or hwnd == 0:
        return
    dwmapi = ctypes.windll.dwmapi
    val = ctypes.c_int(1)
    cb = ctypes.sizeof(val)
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_FORCE_ICONIC_REPRESENTATION, ctypes.byref(val), cb)
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_HAS_ICONIC_BITMAP, ctypes.byref(val), cb)


def try_handle_dwm_thumbnail_messages(
    window: "QWidget", event_type: object, message: object
) -> Optional[Tuple[bool, int]]:
    """
    Handle DWM iconic thumbnail requests. Return (True, 0) when processed.
    """
    if not sys.platform.startswith("win"):
        return None
    if not _is_windows_generic_msg(event_type):
        return None
    msg = _msg_from_native(message)
    if msg is None:
        return None
    if msg.message not in (WM_DWMSENDICONICTHUMBNAIL, WM_DWMSENDICONICLIVEPREVIEWBITMAP):
        return None
    try:
        hwnd_app = int(window.winId())
    except (AttributeError, TypeError, ValueError):
        return None
    if hwnd_app == 0:
        return None
    if int(msg.hwnd) != hwnd_app:
        return None

    mx = (msg.lParam >> 16) & 0xFFFF
    my = msg.lParam & 0xFFFF
    if mx == 0:
        mx = 256
    if my == 0:
        my = 256

    from PyQt5.QtWinExtras import QtWin

    pm = _compose_branded_bitmap(mx, my)
    hbmp = QtWin.toHBITMAP(pm, QtWin.HBitmapPremultipliedAlpha)
    if not hbmp:
        return True, 0
    hbm = int(hbmp)
    gdi32 = ctypes.windll.gdi32
    dwmapi = ctypes.windll.dwmapi

    try:
        if msg.message == WM_DWMSENDICONICTHUMBNAIL:
            dwmapi.DwmSetIconicThumbnail(hwnd_app, hbm, 0)
        else:
            dwmapi.DwmSetIconicLivePreviewBitmap(hwnd_app, hbm, None, DWM_SIT_DISPLAYFRAME)
    finally:
        gdi32.DeleteObject(hbm)

    return True, 0
