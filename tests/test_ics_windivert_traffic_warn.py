"""WinDivert traffic warning must not fire during intentional Kill/Dupe/Lag."""
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


class TestIcsWinDivertTrafficWarn(unittest.TestCase):
    def _main_py(self) -> str:
        return load_main_window_source()

    def test_impairment_guard_exists(self) -> None:
        src = self._main_py()
        self.assertIn('def _ics_victim_impairment_active', src)

    def test_traffic_check_skips_during_impairment(self) -> None:
        src = self._main_py()
        sched = methods_through('_schedule_ics_windivert_traffic_check', '_flow_stable_victim_ip')
        self.assertIn('_ics_victim_impairment_active(ip)', sched)
        check = sched[sched.index('def _check'):]
        self.assertIn('_ics_victim_impairment_active(ip)', check)
        self.assertNotIn('If Kill/Dupe already work', sched)


if __name__ == '__main__':
    unittest.main()
