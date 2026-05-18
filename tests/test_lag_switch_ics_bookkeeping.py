"""Lag Switch on ICS must not use Kill bookkeeping (killer.killed / killed_devices)."""
from __future__ import annotations

import inspect
import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestLagSwitchIcsBookkeeping(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_apply_ics_client_block_supports_for_lag(self) -> None:
        src = self._main_py()
        self.assertIn('for_lag: bool = False', src)

    def test_apply_ics_client_block_skips_kill_state_for_lag(self) -> None:
        src = self._main_py()
        self.assertIn('not for_dupe and not for_lag', src)
        self.assertRegex(
            src,
            r'elif for_lag:\s*\n\s*self\._refresh_table_row_for_mac',
        )

    def test_lag_apply_block_passes_for_lag(self) -> None:
        src = self._main_py()
        self.assertIn('_lag_ics_set_paused', src)
        self.assertIn('for_lag=True', src)

    def test_row_chrome_respects_allow_phase(self) -> None:
        src = self._main_py()
        self.assertIn('_lag_in_allow_phase', src)

    def test_lag_uses_deadline_poll_not_single_shot_only(self) -> None:
        src = self._main_py()
        self.assertIn('_lag_phase_deadline_poll', src)
        self.assertIn('_lag_ics_force_unpause', src)

    def test_stop_lag_switch_does_not_use_removed_lag_timer(self) -> None:
        src = self._main_py()
        stop = src[src.index('def stopLagSwitch'): src.index('def startDupe', src.index('def stopLagSwitch'))]
        self.assertNotIn('lag_timer', stop)


if __name__ == '__main__':
    unittest.main()
