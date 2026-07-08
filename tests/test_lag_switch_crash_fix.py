"""Lag switch deferred start must not crash on mac before local assignment."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestLagSwitchCrashFix(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_lag_deferred_start_binds_work_mac_before_lan_poison_branch(self) -> None:
        src = self._main_py()
        start = src.index('def startLagSwitch')
        toggle = src[start: src.index('def _lag_abort_start', start)]
        deferred = toggle[toggle.index('def _lag_deferred_start'): toggle.index('QTimer.singleShot(0, _lag_deferred_start)')]
        work_mac_bind = deferred.index('work_mac = mac')
        poison_assign = deferred.index('poison_mac = str(work_snap.get(')
        self.assertLess(work_mac_bind, poison_assign)
        self.assertNotIn('\n                    mac = str(work_snap.get(', deferred)


if __name__ == '__main__':
    unittest.main()
