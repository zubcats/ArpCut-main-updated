"""Lag Switch phase countdown (same style as Dupe)."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from gui.main import format_countdown_ms


class TestLagCountdown(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_format_countdown_subminute(self) -> None:
        self.assertEqual(format_countdown_ms(9000), 'Time left: 9.0 s')

    def test_format_countdown_minutes(self) -> None:
        self.assertEqual(format_countdown_ms(125000), 'Time left: 2:05')

    def test_lag_countdown_wired(self) -> None:
        src = self._main_py()
        self.assertIn('lblLagCountdownMain', src)
        self.assertIn('def _tick_lag_countdown', src)
        self.assertIn('def lag_remaining_ms', src)
        self.assertIn('_arm_lag_phase_countdown', src)
        block = src[src.index('def _lag_phase_begin_block'): src.index('def _lag_phase_begin_allow')]
        self.assertIn('_arm_lag_phase_countdown', block)
        allow = src[src.index('def _lag_phase_begin_allow'): src.index('def _lag_phase_deadline_poll')]
        self.assertIn('_arm_lag_phase_countdown', allow)


if __name__ == '__main__':
    unittest.main()
