"""Percent Cut must not self-cancel or crash while clearing Kill for the same victim."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestPercentCutCrashFix(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_pctcut_clears_kill_profile_without_full_kill_off(self) -> None:
        src = self._main_py()
        toggle = src[src.index('def togglePercentCut'): src.index('def stopPercentCut')]
        deferred = toggle[toggle.index('def _pctcut_deferred_start'):]
        self.assertIn('_clear_explicit_kill_for_flow(dict(pct_device))', deferred)
        self.assertNotIn('_run_kill_command(mac, dev, turn_on=False', deferred)

    def test_clear_kill_skips_unkill_for_active_percent_cut_victim(self) -> None:
        src = self._main_py()
        clear = src[src.index('def _clear_explicit_kill_for_flow'): src.index('def _clear_explicit_kill_for_dupe')]
        self.assertIn('percent_cut_device_mac', clear)

    def test_deferred_arm_is_exception_safe(self) -> None:
        src = self._main_py()
        toggle = src[src.index('def togglePercentCut'): src.index('def stopPercentCut')]
        deferred = toggle[toggle.index('def _pctcut_deferred_start'): toggle.index('QTimer.singleShot(0, _pctcut_deferred_start)')]
        self.assertIn('except Exception as exc:', deferred)
        self.assertIn('Percent Cut failed to start', deferred)

    def test_deferred_arm_binds_mac_before_lag_dupe_checks(self) -> None:
        src = self._main_py()
        toggle = src[src.index('def togglePercentCut'): src.index('def stopPercentCut')]
        deferred = toggle[toggle.index('def _pctcut_deferred_start'): toggle.index('QTimer.singleShot(0, _pctcut_deferred_start)')]
        mac_bind = deferred.index("mac = str(pct_device.get('mac')")
        lag_check = deferred.index('self.lag_device_mac == mac')
        self.assertLess(mac_bind, lag_check)

    def test_toggle_validates_mac_and_ip_after_resolve(self) -> None:
        src = self._main_py()
        toggle = src[src.index('def togglePercentCut'): src.index('def stopPercentCut')]
        self.assertIn('_resolve_flow_start_device', toggle)
        self.assertIn('cannot percent cut', toggle.lower())


if __name__ == '__main__':
    unittest.main()
