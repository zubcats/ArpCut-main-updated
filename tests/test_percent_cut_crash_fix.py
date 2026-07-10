"""Percent Cut must not self-cancel or crash while clearing Kill for the same victim."""
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


class TestPercentCutCrashFix(unittest.TestCase):
    def _main_py(self) -> str:
        return load_main_window_source()

    def test_pctcut_clears_kill_profile_without_full_kill_off(self) -> None:
        src = self._main_py()
        toggle = methods_through('togglePercentCut', 'stopPercentCut')
        deferred = toggle[toggle.index('def _pctcut_deferred_start'):]
        self.assertIn('_clear_explicit_kill_for_flow(dict(pct_device))', deferred)
        self.assertNotIn('_run_kill_command(mac, dev, turn_on=False', deferred)

    def test_clear_kill_skips_unkill_for_active_percent_cut_victim(self) -> None:
        src = self._main_py()
        clear = methods_through('_clear_explicit_kill_for_flow', '_clear_explicit_kill_for_dupe')
        self.assertIn('percent_cut_device_mac', clear)

    def test_deferred_arm_is_exception_safe(self) -> None:
        src = self._main_py()
        toggle = methods_through('togglePercentCut', 'stopPercentCut')
        deferred = toggle[toggle.index('def _pctcut_deferred_start'): toggle.index('QTimer.singleShot(0, _pctcut_deferred_start)')]
        self.assertIn('except Exception as exc:', deferred)
        self.assertIn('Percent Cut failed to start', deferred)

    def test_deferred_arm_binds_mac_before_lag_dupe_checks(self) -> None:
        src = self._main_py()
        toggle = methods_through('togglePercentCut', 'stopPercentCut')
        deferred = toggle[toggle.index('def _pctcut_deferred_start'): toggle.index('QTimer.singleShot(0, _pctcut_deferred_start)')]
        mac_bind = deferred.index("mac = str(pct_device.get('mac')")
        lag_check = deferred.index('self.lag_device_mac == mac')
        self.assertLess(mac_bind, lag_check)

    def test_toggle_validates_mac_and_ip_after_resolve(self) -> None:
        src = self._main_py()
        toggle = methods_through('togglePercentCut', 'stopPercentCut')
        self.assertIn('_resolve_flow_start_device', toggle)
        self.assertIn('cannot percent cut', toggle.lower())


if __name__ == '__main__':
    unittest.main()
