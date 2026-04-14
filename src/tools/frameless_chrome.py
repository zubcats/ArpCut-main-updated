"""
Custom title bar + frameless top-level windows (consistent dark chrome).
Windows: WM_NCHITTEST on edges for resize; title bar uses startSystemMove (Qt 5.15+).
"""
from __future__ import annotations

import ctypes
import sys
from typing import Optional, Tuple, Union

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor, QFont, QIcon
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


def _msg_from_native(message: object) -> Optional[ctypes.wintypes.MSG]:
    try:
        addr = int(message)  # sip.voidptr / int
    except (TypeError, ValueError):
        return None
    if addr == 0:
        return None
    try:
        return ctypes.wintypes.MSG.from_address(addr)
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
    ):
        super().__init__(window)
        self.setObjectName("zubcutTitleBar")
        self._window = window
        self._maximizable = maximizable
        self.setFixedHeight(36)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QFrame#zubcutTitleBar {
                background-color: #2d323c;
                border: none;
                border-bottom: 1px solid #3d4a5c;
            }
            QFrame#zubcutTitleBar QLabel#titleLabel {
                color: #e8eaed;
                font-size: 13px;
            }
            QFrame#zubcutTitleBar QToolButton {
                background-color: transparent;
                border: 1px solid #000000;
                border-radius: 4px;
                padding: 3px;
                min-width: 28px;
                min-height: 24px;
                color: #8b909a;
            }
            QFrame#zubcutTitleBar QToolButton:hover {
                background-color: #40454f;
                border: 1px solid #000000;
                color: #aeb4bf;
            }
            QFrame#zubcutTitleBar QToolButton:pressed {
                background-color: #353942;
                border: 1px solid #000000;
                color: #8b909a;
            }
            QFrame#zubcutTitleBar QToolButton#closeButton:hover {
                background-color: #c0392b;
                border: 1px solid #000000;
                color: #f2f2f2;
            }
            QFrame#zubcutTitleBar QToolButton#closeButton:pressed {
                background-color: #a93226;
                border: 1px solid #000000;
                color: #f2f2f2;
            }
            """
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 6, 0)
        row.setSpacing(6)

        _icon_px = 30
        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(_icon_px, _icon_px)
        if icon is not None and not icon.isNull():
            self._icon_label.setPixmap(icon.pixmap(_icon_px, _icon_px))
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
