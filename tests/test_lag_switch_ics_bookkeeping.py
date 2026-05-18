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

    def test_lag_uses_single_shot_phase_timer(self) -> None:
        src = self._main_py()
        self.assertIn('_lag_phase_end_timer_fired', src)
        self.assertIn('_lag_ics_force_unpause', src)

    def test_stop_lag_switch_does_not_use_removed_lag_timer(self) -> None:
        src = self._main_py()
        stop = src[src.index('def stopLagSwitch'): src.index('def startDupe', src.index('def stopLagSwitch'))]
        self.assertNotIn('lag_timer', stop)

    def test_stop_lag_switch_releases_instantly_like_dupe(self) -> None:
        src = self._main_py()
        stop = src[src.index('def stopLagSwitch'): src.index('def startDupe', src.index('def stopLagSwitch'))]
        self.assertIn('_ics_emergency_release', stop)
        self.assertIn('_lag_ics_force_unpause', stop)
        self.assertIn('_cancel_lag_block_reassert', stop)
        self.assertNotIn('QTimer.singleShot(0, _lag_teardown)', stop)
        self.assertNotIn('_schedule_flow_off_reinforce', stop)

    def test_lag_allow_phase_resumes_windivert(self) -> None:
        src = self._main_py()
        self.assertIn('_lag_ics_resume_allow_phase', src)
        self.assertIn('_flow_stable_victim_ip', src)
        allow = src[src.index('def _lag_phase_begin_allow'): src.index('def _lag_apply_block')]
        self.assertIn('_lag_ics_resume_allow_phase', allow)
        self.assertIn('_cancel_lag_block_reassert', allow)
        self.assertIn('_lag_schedule_phase', allow)

    def test_release_windivert_unpauses_without_gate_match(self) -> None:
        src = self._main_py()
        rel = src[src.index('def _release_ics_windivert_block'): src.index('def _schedule_ics_hotspot_heal')]
        self.assertNotIn('self._ics_gate_matches_device(device)', rel)


if __name__ == '__main__':
    unittest.main()
