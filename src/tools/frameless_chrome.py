"""
Custom title bar + frameless top-level windows (consistent dark chrome).
Windows: WM_NCHITTEST on edges for resize; title bar uses startSystemMove (Qt 5.15+).
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Optional, Tuple, Union

from PyQt5.QtCore import QEvent, QObject, QRectF, Qt
from PyQt5.QtGui import QCursor, QFont, QIcon, QPainterPath, QRegion
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from constants import *

# Backward compatibility for older packaged constants modules.
WINDOW_CORNER_RADIUS_PX = int(globals().get('WINDOW_CORNER_RADIUS_PX', 12))


def _experimental_charcoal_titlebar() -> bool:
    """Match utils_gui charcoal chrome; channel does not change title bar palette."""
    return True

# Title-bar control glyphs (styled via QSS color; standard pixmaps cannot be tinted).
_GLYPH_MIN = "\u2212"  # minus
_GLYPH_MAX = "\u25A1"  # square (maximize)
_GLYPH_RESTORE = "\u2750"  # restore
_GLYPH_CLOSE = "\u00D7"  # close

# —— Windows resize borders (client coords, logical pixels) ——
_BORDER = 5
WM_NCHITTEST = 0x0084
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17


def _is_windows_generic_msg(event_type: object) -> bool:
    if isinstance(event_type, bytes):
        return b"windows_generic_MSG" in event_type or b"windows_dispatcher" in event_type
    s = str(event_type)
    return "windows_generic_MSG" in s or "windows_dispatcher" in s


def _msg_from_native(message: object) -> Optional[wintypes.MSG]:
    try:
        addr = int(message)  # sip.voidptr / int
    except (TypeError, ValueError):
        return None
    if addr == 0:
        return None
    try:
        return wintypes.MSG.from_address(addr)
    except (ValueError, ctypes.ArgumentError):
        return None


def try_handle_win_nchittest(
    window: QWidget, event_type: object, message: object
) -> Optional[Tuple[bool, int]]:
    """Return (True, lresult) for WM_NCHITTEST resize borders; else None."""
    if not sys.platform.startswith("win"):
        return None
    if not _is_windows_generic_msg(event_type):
        return None
    if window.isMaximized() or window.isFullScreen():
        return None
    msg = _msg_from_native(message)
    if msg is None or msg.message != WM_NCHITTEST:
        return None
    # Screen coordinates (same moment as the message; frameGeometry is global).
    pos = QCursor.pos()
    x, y = pos.x(), pos.y()
    g = window.frameGeometry()
    left, top, right, bottom = g.left(), g.top(), g.right(), g.bottom()
    on_left = x < left + _BORDER
    on_right = x >= right - _BORDER
    on_top = y < top + _BORDER
    on_bottom = y >= bottom - _BORDER
    if on_top and on_left:
        return True, HTTOPLEFT
    if on_top and on_right:
        return True, HTTOPRIGHT
    if on_bottom and on_left:
        return True, HTBOTTOMLEFT
    if on_bottom and on_right:
        return True, HTBOTTOMRIGHT
    if on_left:
        return True, HTLEFT
    if on_right:
        return True, HTRIGHT
    if on_top:
        return True, HTTOP
    if on_bottom:
        return True, HTBOTTOM
    return None


class FramelessResizableMixin:
    """Mixin: add as first base before QMainWindow / QDialog. Enables edge resize on Windows."""

    def nativeEvent(
        self, event_type: object, message: object
    ) -> Tuple[bool, Union[int, bytes]]:
        r = try_handle_win_nchittest(self, event_type, message)
        if r is not None:
            return r
        return super().nativeEvent(event_type, message)


class CustomTitleBar(QFrame):
    """Dark caption: icon, title, min / max / close."""

    def __init__(
        self,
        window: QWidget,
        title: str,
        icon: Optional[QIcon],
        *,
        maximizable: bool = True,
        caption_accent: Optional[str] = None,
    ):
        super().__init__(window)
        self.setObjectName("zubcutTitleBar")
        self._window = window
        self._maximizable = maximizable
        self.setFixedHeight(36)
        self.setAttribute(Qt.WA_StyledBackground, True)
        if caption_accent:
            _bg = '#2b2b2b'
            _bd = caption_accent
            _btn_h, _btn_p = '#3d524f', '#354846'
            _muted, _hi = '#9a9a9a', '#eef1f0'
        elif _experimental_charcoal_titlebar():
            _bg, _bd = '#2b2b2b', '#3d3d3d'
            _btn_h, _btn_p = '#383838', '#323232'
            _muted, _hi = '#9a9a9a', '#d0d0d0'
        else:
            _bg, _bd = '#2d323c', '#3d4a5c'
            _btn_h, _btn_p = '#3a3f49', '#353942'
            _muted, _hi = '#8b909a', '#aeb4bf'
        _tb_hover_border = _bd if caption_accent else _btn_h
        _tb_press_border = _bd if caption_accent else _btn_p
        self.setStyleSheet(
            f"""
            QFrame#zubcutTitleBar {{
                background-color: {_bg};
                border: none;
                border-bottom: 1px solid {_bd};
                border-top-left-radius: {WINDOW_CORNER_RADIUS_PX}px;
                border-top-right-radius: {WINDOW_CORNER_RADIUS_PX}px;
            }}
            QFrame#zubcutTitleBar QLabel#titleLabel {{
                color: #e8eaed;
                font-size: 13px;
                background: transparent;
            }}
            QFrame#zubcutTitleBar QLabel#logoLabel {{
                border: none;
                background: transparent;
            }}
            QFrame#zubcutTitleBar QToolButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 3px;
                min-width: 22px;
                min-height: 22px;
                color: {_muted};
            }}
            QFrame#zubcutTitleBar QToolButton:hover {{
                background-color: {_btn_h};
                border: 1px solid {_tb_hover_border};
                color: {_hi};
            }}
            QFrame#zubcutTitleBar QToolButton:pressed {{
                background-color: {_btn_p};
                border: 1px solid {_tb_press_border};
                color: {_muted};
            }}
            QFrame#zubcutTitleBar QToolButton#closeButton:hover {{
                background-color: #c0392b;
                border: 1px solid #c0392b;
                color: #f2f2f2;
            }}
            QFrame#zubcutTitleBar QToolButton#closeButton:pressed {{
                background-color: #a93226;
                border: 1px solid #a93226;
                color: #f2f2f2;
            }}
            """
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 6, 0)
        row.setSpacing(6)

        _icon_px = 32
        _icon_box_px = _icon_px + 2
        self._icon_label = QLabel(self)
        self._icon_label.setObjectName("logoLabel")
        self._icon_label.setFixedSize(_icon_box_px, _icon_box_px)
        self._icon_label.setAlignment(Qt.AlignCenter)
        if icon is not None and not icon.isNull():
            pm = icon.pixmap(_icon_box_px * 2, _icon_box_px * 2).scaled(
                _icon_px,
                _icon_px,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._icon_label.setPixmap(pm)
        else:
            self._icon_label.hide()

        self._title = QLabel(title, self)
        self._title.setObjectName("titleLabel")
        self._title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        _cap_font = QFont(self.font())
        _cap_font.setPointSize(13)
        _cap_font.setBold(True)

        self._btn_min = QToolButton(self)
        self._btn_min.setText(_GLYPH_MIN)
        self._btn_min.setIcon(QIcon())
        self._btn_min.setFont(_cap_font)
        self._btn_min.clicked.connect(self._window.showMinimized)

        self._btn_max = QToolButton(self)
        self._btn_max.setText(_GLYPH_MAX)
        self._btn_max.setIcon(QIcon())
        self._btn_max.setFont(_cap_font)
        self._btn_max.clicked.connect(self._toggle_max)
        if not maximizable:
            self._btn_max.hide()

        self._btn_close = QToolButton(self)
        self._btn_close.setObjectName("closeButton")
        self._btn_close.setText(_GLYPH_CLOSE)
        self._btn_close.setIcon(QIcon())
        self._btn_close.setFont(_cap_font)
        self._btn_close.clicked.connect(self._window.close)

        row.addWidget(self._icon_label)
        row.addWidget(self._title, 1)
        row.addWidget(self._btn_min, 0, Qt.AlignVCenter)
        row.addWidget(self._btn_max, 0, Qt.AlignVCenter)
        row.addWidget(self._btn_close, 0, Qt.AlignVCenter)

    def setTitleText(self, text: str) -> None:
        self._title.setText(text)

    def _toggle_max(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self._sync_max_icon()

    def _sync_max_icon(self) -> None:
        if not self._maximizable:
            return
        self._btn_max.setText(
            _GLYPH_RESTORE if self._window.isMaximized() else _GLYPH_MAX
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.pos())
            if child not in (self._btn_min, self._btn_max, self._btn_close):
                w = self._window.windowHandle()
                if w is not None:
                    w.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._maximizable:
            child = self.childAt(event.pos())
            if child not in (self._btn_min, self._btn_max, self._btn_close):
                self._toggle_max()
        super().mouseDoubleClickEvent(event)


def setup_frameless_main_window(
    window: QMainWindow,
    title: str,
    icon: Optional[QIcon],
    *,
    maximizable: bool = True,
) -> None:
    """Remove native caption; insert CustomTitleBar above existing central widget."""
    window.setWindowFlags(window.windowFlags() | Qt.FramelessWindowHint)
    central = window.takeCentralWidget()
    if central is None:
        return
    wrapper = QWidget()
    vl = QVBoxLayout(wrapper)
    vl.setContentsMargins(0, 0, 0, 0)
    vl.setSpacing(0)
    bar = CustomTitleBar(window, title, icon, maximizable=maximizable)
    vl.addWidget(bar)
    vl.addWidget(central, 1)
    window.setCentralWidget(wrapper)
    window.setWindowTitle(title)


def _update_top_level_round_mask(widget: QWidget) -> None:
    """Clip the entire top-level window to a rounded rect (fixes square corners / bleed-through)."""
    if widget is None or not widget.isWindow():
        return
    if widget.isMaximized() or widget.isFullScreen():
        widget.clearMask()
        return
    w, h = widget.width(), widget.height()
    if w < 2 or h < 2:
        return
    r = min(
        float(WINDOW_CORNER_RADIUS_PX),
        max(2.0, min(float(w), float(h)) / 2.0 - 1.0),
    )
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, float(w), float(h)), r, r)
    # QRegion expects an integer polygon on PyQt5; PolygonF can raise at runtime.
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


class _WindowChromeEventFilter(QObject):
    """First Show: DWM hints. Show/resize/state: rounded QWidget mask for frameless windows."""

    def __init__(self, parent_widget: QWidget):
        super().__init__(parent_widget)
        self._dwm_applied = False

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Show and not self._dwm_applied:
            self._dwm_applied = True
            _apply_win32_dwm_window_chrome(obj)
        if t in (QEvent.Show, QEvent.Resize, QEvent.WindowStateChange):
            _update_top_level_round_mask(obj)
        return False


def _apply_win32_dwm_window_chrome(widget) -> None:
    """
    Same DWM calls on every Windows version we support: immersive dark + optional round-corners hint.
    Older builds ignore attributes they do not implement. Rounded outline is always from the Qt mask.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        hwnd_p = ctypes.c_void_p(hwnd)
    except Exception:
        return

    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(
            hwnd_p,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark),
            ctypes.sizeof(dark),
        )
    except Exception:
        pass

    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        preference = ctypes.c_uint(DWMWCP_ROUND)
        dwm.DwmSetWindowAttribute(
            hwnd_p,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
    except Exception:
        pass


def register_window_surface_effects(window_widget) -> None:
    """Translucent client + DWM hints (same path on all Windows); Qt mask provides the real rounded clip."""
    if window_widget is None:
        return
    use_translucent = getattr(window_widget, "_zubcut_use_translucent_surface", True)
    window_widget.setAttribute(Qt.WA_TranslucentBackground, bool(use_translucent))
    if getattr(window_widget, "_zubcut_round_filter_installed", False):
        return
    window_widget._zubcut_round_filter_installed = True
    window_widget.installEventFilter(_WindowChromeEventFilter(window_widget))


def sync_translucent_chrome(windows) -> None:
    """Per-pixel alpha with the desktop behind the dark theme chrome."""
    for w in windows:
        register_window_surface_effects(w)
