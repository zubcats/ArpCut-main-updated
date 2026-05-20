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
        self.assertEqual(format_countdown_ms(9000), 'Time left: 9 s')
        self.assertEqual(format_countdown_ms(2500), 'Time left: 3 s')

    def test_format_countdown_minutes(self) -> None:
        self.assertEqual(format_countdown_ms(125000), 'Time left: 2:05')

    def test_countdown_uses_background_net(self) -> None:
        src = self._main_py()
        self.assertIn('def _run_on_flow_net_thread', src)
        self.assertIn('flow_net_main_done', src)
        self.assertIn('_on_flow_net_main_done', src)
        self.assertNotIn('_pump_ui_light', src)

    def test_lag_countdown_wired(self) -> None:
        src = self._main_py()
        self.assertIn('lblLagCountdownMain', src)
        self.assertIn('def _tick_lag_countdown', src)
        self.assertIn('def lag_remaining_ms', src)
        self.assertIn('_arm_lag_phase_countdown', src)
        block = src[src.index('def _lag_phase_begin_block'): src.index('def _lag_phase_begin_allow')]
        self.assertIn('_arm_lag_phase_countdown', block)
        allow = src[src.index('def _lag_phase_begin_allow'): src.index('def _lag_apply_block')]
        self.assertIn('_lag_schedule_phase', allow)
        self.assertIn('_lag_apply_allow_phase_sync', allow)
        self.assertIn('_arm_lag_phase_countdown', allow)
        tick = src[src.index('def _tick_lag_countdown'): src.index('def _lag_phase_begin_block')]
        self.assertNotIn('_lag_ics_force_unpause', tick)

    def test_allow_phase_uses_same_countdown_format(self) -> None:
        from gui.main import ZubCutApp

        self.assertEqual(ZubCutApp._lag_countdown_label(True, 1500), 'Time left: 2 s')
        self.assertEqual(ZubCutApp._lag_countdown_label(False, 9000), 'Time left: 9 s')

    def test_phase_flag_before_timing_sync_in_begin(self) -> None:
        src = self._main_py()
        block = src[src.index('def _lag_phase_begin_block'): src.index('def _lag_phase_begin_allow')]
        allow = src[src.index('def _lag_phase_begin_allow'): src.index('def _lag_apply_block')]
        self.assertLess(
            block.index('_lag_in_allow_phase = False'),
            block.index('_sync_lag_timing_values_from_ui'),
        )
        self.assertLess(
            allow.index('_lag_in_allow_phase = True'),
            allow.index('_sync_lag_timing_values_from_ui'),
        )

    def test_tick_advances_phase_at_zero(self) -> None:
        src = self._main_py()
        tick = src[src.index('def _tick_lag_countdown'): src.index('def _lag_phase_begin_block')]
        self.assertIn('_lag_request_phase_advance', tick)
        self.assertIn('rem <= 0', tick)
        self.assertNotIn('_lag_phase_end_timer_fired()', tick)

    def test_phase_advance_deferred_not_recursive(self) -> None:
        src = self._main_py()
        self.assertIn('def _lag_request_phase_advance', src)
        self.assertIn('def _lag_do_phase_advance', src)
        self.assertIn('_lag_phase_advance_pending', src)
        req = src[src.index('def _lag_request_phase_advance'): src.index('def _lag_phase_end_timer_fired')]
        self.assertIn('QTimer.singleShot(0, self._lag_do_phase_advance)', req)
        fired = src[src.index('def _lag_phase_end_timer_fired'): src.index('def _lag_do_phase_advance')]
        self.assertIn('_lag_do_phase_advance', fired)
        self.assertNotIn('_lag_request_phase_advance', fired)
        begin = src[src.index('def _lag_phase_begin_block'): src.index('def _lag_phase_begin_allow')]
        self.assertNotIn('_lag_do_phase_advance', begin)


if __name__ == '__main__':
    unittest.main()
