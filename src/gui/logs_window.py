"""Advanced log viewer — full messages and in-app diagnostic tool buttons."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
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

from constants import APP_DISPLAY_NAME, UI_LOG_RESTORE_FG, UI_LOG_VICTIM_BLOCK_FG
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
    c = str(color or 'white').strip()
    lowered = c.lower()
    if lowered.startswith('#') and len(lowered) in (4, 7, 9):
        return lowered
    return {
        'white': '#e8e8e8',
        'red': '#e06060',
        'gray': '#9a9a9a',
        'grey': '#9a9a9a',
        'green': '#43b581',
        'yellow': '#f0c040',
        'aqua': '#5ec4c4',
        'ui_log_victim_block_fg': UI_LOG_VICTIM_BLOCK_FG.lower(),
        'ui_log_restore_fg': UI_LOG_RESTORE_FG.lower(),
    }.get(lowered, lowered if lowered.startswith('#') else '#e8e8e8')


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

        # Same object name as Designer windows so translucent_main_chrome_qss
        # paints charcoal (#141414) instead of qdarkstyle blue-grey.
        root = QWidget(self)
        root.setObjectName('centralwidget')
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            'Status messages from the main window. Select a line to read the full text.',
            root,
        )
        hint.setObjectName('logsHintLabel')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #9a9a9a; font-size: 11px;')
        layout.addWidget(hint)

        self._splitter = QSplitter(Qt.Vertical, root)
        self._splitter.setObjectName('logsSplitter')
        self._list = QListWidget(self._splitter)
        self._list.setObjectName('logsHistoryList')
        mono = QFont('Consolas' if __import__('sys').platform.startswith('win') else 'Menlo', 10)
        self._list.setFont(mono)
        self._list.setAlternatingRowColors(True)
        self._list.currentRowChanged.connect(self._on_row_changed)

        detail_wrap = QWidget(self._splitter)
        detail_wrap.setObjectName('logsDetailWrap')
        detail_layout = QVBoxLayout(detail_wrap)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(4)
        detail_heading = QLabel('Full message', detail_wrap)
        detail_heading.setObjectName('logsDetailHeading')
        detail_layout.addWidget(detail_heading)
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

        diag_panel = QFrame(root)
        diag_panel.setObjectName('logsDiagPanel')
        diag_layout = QVBoxLayout(diag_panel)
        diag_layout.setContentsMargins(10, 8, 10, 8)
        diag_layout.setSpacing(6)
        diag_heading = QLabel('Diagnostic tools', diag_panel)
        diag_heading.setObjectName('logsDiagHeading')
        diag_layout.addWidget(diag_heading)
        diag_hint = QLabel(
            'Quick check runs all diagnostics (Npcap/capture, Wi-Fi link, LAN Kill, '
            'Clumsy hotspot). Turn Analysis ON to baseline the selected victim, then '
            'check DURING the cut and AFTER restore (ZubCut host + victim) for Kill / '
            'Lag / Dupe / Percent Cut — never delays instant cut. Reports save to '
            'Desktop\\ZubCut Diagnostics.',
            diag_panel,
        )
        diag_hint.setObjectName('logsDiagHint')
        diag_hint.setWordWrap(True)
        diag_layout.addWidget(diag_hint)
        diag_btns = QHBoxLayout()
        diag_btns.setSpacing(8)
        self._btn_quick_check = QPushButton('Quick check', diag_panel)
        self._btn_quick_check.setObjectName('logsDiagQuickBtn')
        self._btn_quick_check.setToolTip(
            'All-in-one support diagnostic: Active path, Capture stack (Npcap sniffer/L2), '
            'environment, LAN path, Hotspot path, and this PC\'s Wi-Fi link. '
            'Saves ZubCut-Quick-Diag-*.txt in Desktop\\ZubCut Diagnostics and opens it in Notepad.'
        )
        self._btn_quick_check.clicked.connect(self._run_quick_check)
        diag_btns.addWidget(self._btn_quick_check)
        self._btn_analysis = QPushButton('Analysis', diag_panel)
        self._btn_analysis.setObjectName('logsDiagAnalysisBtn')
        self._btn_analysis.setCheckable(True)
        self._btn_analysis.setToolTip(
            'When ON: BEFORE baselines the selected victim while idle; DURING checks the '
            'cut after arm; AFTER checks restore when you turn OFF. Also verifies ZubCut '
            'host health (adapter, gateway MAC, Npcap L2, IP forwarding, ARP).\n\n'
            'For a clear Dupe Analysis: leave Analysis ON a few seconds, then set Dupe '
            'duration to at least 8000 ms (8s). 5000 ms (5s) is often too short once arm + '
            'settle + sniff run — DURING can miss the cut window and falsely FAIL.\n\n'
            'Overall SUCCESS only when BEFORE/DURING/AFTER pass and a full cut is proven '
            '(MITM + hard-drop + live drop/traffic evidence). Does not delay instant cut. '
            'One report at the end with BEFORE + DURING + AFTER in '
            'Desktop\\ZubCut Diagnostics\\ZubCut-Analysis-*.txt (opens in Notepad).'
        )
        try:
            self._btn_analysis.setChecked(bool(getattr(app, 'cut_analysis_enabled', lambda: False)()))
        except Exception:
            self._btn_analysis.setChecked(False)
        self._btn_analysis.toggled.connect(self._on_analysis_toggled)
        diag_btns.addWidget(self._btn_analysis)
        diag_btns.addStretch(1)
        diag_layout.addLayout(diag_btns)
        layout.addWidget(diag_panel)

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
        try:
            enabled = bool(self._app.cut_analysis_enabled())
            if self._btn_analysis.isChecked() != enabled:
                self._btn_analysis.blockSignals(True)
                self._btn_analysis.setChecked(enabled)
                self._btn_analysis.blockSignals(False)
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

    def _run_quick_check(self) -> None:
        """Launch the friend-support Quick Network Diag in elevated PowerShell."""
        try:
            from tools.support_quick_diag import launch_quick_network_diag_elevated

            ok, message = launch_quick_network_diag_elevated()
        except Exception as exc:
            ok, message = False, f'Quick check failed: {exc}'
        try:
            self._app.log(message, 'gray' if ok else 'red')
        except Exception:
            pass

    def _on_analysis_toggled(self, checked: bool) -> None:
        """Enable/disable deep cut Analysis after Kill/Lag/Dupe/Percent Cut arm."""
        try:
            self._app.set_cut_analysis_enabled(bool(checked))
        except Exception as exc:
            try:
                self._app.log(f'Analysis toggle failed: {exc}', 'red')
            except Exception:
                pass
