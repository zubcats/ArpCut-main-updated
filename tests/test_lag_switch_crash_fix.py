"""Lag switch deferred start must not crash on mac before local assignment."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _gui_source import load_main_window_source, methods_through, method_src


class TestLagSwitchCrashFix(unittest.TestCase):
    def _main_py(self) -> str:
        return load_main_window_source()

    def test_lag_deferred_start_binds_work_mac_before_lan_poison_branch(self) -> None:
        src = self._main_py()
        toggle = methods_through('startLagSwitch', '_lag_abort_start')
        deferred = toggle[toggle.index('def _lag_deferred_start'): toggle.index('QTimer.singleShot(0, _lag_deferred_start)')]
        work_mac_bind = deferred.index('work_mac = mac')
        poison_assign = deferred.index('poison_mac = str(work_snap.get(')
        self.assertLess(work_mac_bind, poison_assign)
        self.assertNotIn('\n                    mac = str(work_snap.get(', deferred)


    def test_lag_resolved_victim_skips_ping_while_mitm_armed(self) -> None:
        src = self._main_py()
        block = methods_through('_lag_resolved_victim', 'stopLagSwitch')
        self.assertIn('def _lag_skip_live_resolve', src)
        self.assertIn('if not self._lag_skip_live_resolve(merged):', block)

    def test_lag_lan_mitm_stays_warm_across_cycles(self) -> None:
        src = self._main_py()
        warm = methods_through('_lag_lan_mitm_warm', '_lag_clear_block_only')
        self.assertIn('or bool(self.lag_active)', warm)


if __name__ == '__main__':
    unittest.main()
