"""Logs window wiring — history buffer and main-window entry points."""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestLogsWindowWiring(unittest.TestCase):
    def test_main_log_keeps_history(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        block = src[src.index('def log(self, text, color'): src.index('def _append_log_history')]
        self.assertIn('_append_log_history', block)

    def test_status_line_context_menu_opens_logs(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertNotIn("self.btnLogs = QPushButton('Logs'", src)
        self.assertIn('_on_status_log_context_menu', src)
        self.assertIn('Open Logs', src)
        self.assertIn('log_color_to_hex', src)
        self.assertIn('setStyleSheet', src[src.index('def _apply_status_strip_elide'): src.index('def log(self')])

    def test_log_color_semantic_palette(self) -> None:
        path = os.path.join(_SRC, 'gui', 'logs_window.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('UI_LOG_VICTIM_BLOCK_FG', src)
        self.assertIn('UI_LOG_RESTORE_FG', src)
        self.assertIn("'ui_log_victim_block_fg'", src)
        self.assertIn("'ui_log_restore_fg'", src)

    def test_logs_window_module(self) -> None:
        path = os.path.join(_SRC, 'gui', 'logs_window.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('class LogsWindow', src)
        self.assertIn('class LogEntry', src)
        self.assertIn('def sync_entries', src)
        self.assertIn('Diagnostic tools — coming soon', src)
        self.assertIn("setObjectName('centralwidget')", src)
        self.assertIn("setObjectName('logsHistoryList')", src)
        self.assertIn("setObjectName('logsDetailPane')", src)
        self.assertIn("setObjectName('logsSplitter')", src)

    def test_logs_window_matches_main_charcoal_theme(self) -> None:
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('QListWidget#logsHistoryList', src)
        self.assertIn('QPlainTextEdit#logsDetailPane', src)
        self.assertIn('QSplitter#logsSplitter', src)
        block = src[
            src.index('QListWidget#logsHistoryList'):
            src.index('QLabel#logsDetailHeading')
        ]
        self.assertIn('background-color: #000000', block)
        self.assertNotIn('#19232D', block)
        self.assertNotIn('#1A72BB', block)


if __name__ == '__main__':
    unittest.main()
