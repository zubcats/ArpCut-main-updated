"""WinDivert traffic warning must not fire during intentional Kill/Dupe/Lag."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestIcsWinDivertTrafficWarn(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_impairment_guard_exists(self) -> None:
        src = self._main_py()
        self.assertIn('def _ics_victim_impairment_active', src)

    def test_traffic_check_skips_during_impairment(self) -> None:
        src = self._main_py()
        sched = src[
            src.index('def _schedule_ics_windivert_traffic_check'): src.index(
                'def _flow_stable_victim_ip'
            )
        ]
        self.assertIn('_ics_victim_impairment_active(ip)', sched)
        check = sched[sched.index('def _check'):]
        self.assertIn('_ics_victim_impairment_active(ip)', check)
        self.assertNotIn('If Kill/Dupe already work', sched)


if __name__ == '__main__':
    unittest.main()
