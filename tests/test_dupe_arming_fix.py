"""Dupe must arm MITM (not freeze on Arming) on home LAN Wi-Fi."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestDupeArmingFix(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_dupe_impairment_is_live_helper(self) -> None:
        src = self._main_py()
        self.assertIn('def _dupe_impairment_is_live', src)

    def test_preblocked_path_verifies_live_before_arm_ok(self) -> None:
        src = self._main_py()
        fn = src[src.index('def _run_dupe_arm_command'): src.index('def _apply_dupe_deferred')]
        pre = fn[fn.index("if getattr(self, '_dupe_preblocked', False)"):]
        self.assertIn('_dupe_impairment_is_live(dev)', pre)
        self.assertIn('preblock did not stick', pre.lower())

    def test_deferred_start_does_not_stop_dupe_mid_arm(self) -> None:
        src = self._main_py()
        start = src[src.index('def startDupe'): src.index('def dupe_remaining_ms')]
        deferred = start[start.index('def _dupe_deferred_start'): start.index('QTimer.singleShot(0, _dupe_deferred_start)')]
        self.assertNotIn('stopDupe', deferred)

    def test_clear_kill_skips_unkill_for_active_dupe_victim(self) -> None:
        src = self._main_py()
        clear = src[src.index('def _clear_explicit_kill_for_flow'): src.index('def _clear_explicit_kill_for_dupe')]
        self.assertIn('dupe_device_mac', clear)

    def test_background_dupe_release_skips_context_refresh(self) -> None:
        src = self._main_py()
        stop = src[src.index('def stopDupe'): src.index('def _updateDupeButtonState', src.index('def stopDupe'))]
        self.assertIn('refresh_context=False', stop)


if __name__ == '__main__':
    unittest.main()
