"""Advanced log viewer — full messages and room for future diagnostic tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from constants import APP_DISPLAY_NAME
from tools.frameless_chrome import FramelessResizableMixin, setup_frameless_main_window
from tools.utils_gui import register_window_surface_effects

if TYPE_CHECKING:
    from gui.main import ZubCutApp


@dataclass(frozen=True)
class LogEntry:
    """One status-strip log line with timestamp and display color token."""

    ts: datetime
    text: str
    color: str


def log_color_to_hex(color: str) -> str:
    c = str(color or 'white').strip().lower()
    if c.startswith('#') and len(c) in (4, 7, 9):
        return c
    return {
        'white': '#e8e8e8',
        'red': '#e06060',
        'gray': '#9a9a9a',
        'grey': '#9a9a9a',
        'green': '#43b581',
        'yellow': '#f0c040',
        'aqua': '#5ec4c4',
    }.get(c, c if c.startswith('#') else '#e8e8e8')


class LogsWindow(FramelessResizableMixin, QMainWindow):
    """Scrollable log history with a detail pane for the full selected message."""

    def __init__(self, app: 'ZubCutApp', icon):
        super().__init__()
        self._app = app
        self.icon = icon
        self.setWindowIcon(icon)
        self.setObjectName('zubcutAuxiliaryWindow')
        self.setWindowTitle(f'{APP_DISPLAY_NAME} — Logs')
        self.setMinimumSize(520, 360)
        self.resize(640, 480)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            'Status messages from the main window. Select a line to read the full text.',
            root,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #9a9a9a; font-size: 11px;')
        layout.addWidget(hint)

        self._splitter = QSplitter(Qt.Vertical, root)
        self._list = QListWidget(self._splitter)
        self._list.setObjectName('logsHistoryList')
        mono = QFont('Consolas' if __import__('sys').platform.startswith('win') else 'Menlo', 10)
        self._list.setFont(mono)
        self._list.setAlternatingRowColors(True)
        self._list.currentRowChanged.connect(self._on_row_changed)

        detail_wrap = QWidget(self._splitter)
        detail_layout = QVBoxLayout(detail_wrap)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(4)
        detail_layout.addWidget(QLabel('Full message', detail_wrap))
        self._detail = QPlainTextEdit(detail_wrap)
        self._detail.setObjectName('logsDetailPane')
        self._detail.setReadOnly(True)
        self._detail.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._detail.setFont(mono)
        detail_layout.addWidget(self._detail)

        self._splitter.addWidget(self._list)
        self._splitter.addWidget(detail_wrap)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        layout.addWidget(self._splitter, 1)

        self._diag_group = QLabel('Diagnostic tools — coming soon', root)
        self._diag_group.setAlignment(Qt.AlignCenter)
        self._diag_group.setStyleSheet(
            'color: #6a6a6a; font-size: 11px; padding: 8px; '
            'border: 1px dashed #3a3a3a; border-radius: 4px;'
        )
        layout.addWidget(self._diag_group)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn_copy = QPushButton('Copy message', root)
        self._btn_copy.clicked.connect(self._copy_selected)
        btn_row.addWidget(self._btn_copy)
        self._btn_clear = QPushButton('Clear log', root)
        self._btn_clear.clicked.connect(self._clear_log)
        btn_row.addWidget(self._btn_clear)
        layout.addLayout(btn_row)

        self._entries: List[LogEntry] = []

        setup_frameless_main_window(self, self.windowTitle(), self.icon, maximizable=True)
        register_window_surface_effects(self)

    def sync_entries(self, entries: Iterable[LogEntry]) -> None:
        """Replace list contents from the main window history."""
        self._entries = list(entries)
        prev_row = self._list.currentRow()
        self._list.blockSignals(True)
        self._list.clear()
        for idx, entry in enumerate(self._entries):
            preview = entry.text.replace('\n', ' ').strip()
            if len(preview) > 120:
                preview = preview[:119] + '\u2026'
            ts = entry.ts.strftime('%H:%M:%S')
            item = QListWidgetItem(f'{ts}  {preview}')
            item.setData(Qt.UserRole, idx)
            item.setForeground(QColor(log_color_to_hex(entry.color)))
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._entries:
            row = prev_row if 0 <= prev_row < len(self._entries) else len(self._entries) - 1
            self._list.setCurrentRow(row)
        else:
            self._detail.clear()
            self._btn_copy.setEnabled(False)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.sync_entries(self._app.log_entries())
        except Exception:
            pass

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._entries):
            self._detail.clear()
            self._btn_copy.setEnabled(False)
            return
        entry = self._entries[row]
        header = entry.ts.strftime('%Y-%m-%d %H:%M:%S')
        self._detail.setPlainText(f'[{header}]\n{entry.text}')
        self._btn_copy.setEnabled(bool(entry.text.strip()))

    def _copy_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._entries):
            return
        text = self._entries[row].text
        if not text:
            return
        try:
            from pyperclip import copy as clip_copy

            clip_copy(text)
        except Exception:
            QApplication.clipboard().setText(text)
        try:
            self._app.log('Copied log message to clipboard', 'gray')
        except Exception:
            pass

    def _clear_log(self) -> None:
        try:
            self._app.clear_log_history()
        except Exception:
            pass
        self.sync_entries(())
