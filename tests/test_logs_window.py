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
        self.assertIn('setAutoFillBackground(False)', src)

    def test_logs_window_module(self) -> None:
        path = os.path.join(_SRC, 'gui', 'logs_window.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('class LogsWindow', src)
        self.assertIn('class LogEntry', src)
        self.assertIn('def sync_entries', src)
        self.assertIn('Diagnostic tools — coming soon', src)


if __name__ == '__main__':
    unittest.main()
