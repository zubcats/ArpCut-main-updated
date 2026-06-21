"""Percent Cut must not arm Kill's 0% traffic-cut forwarder before partial pass ratio."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestPercentCutKill(unittest.TestCase):
    @staticmethod
    def _killer_py() -> str:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_kill_supports_traffic_cut_flag(self) -> None:
        src = self._killer_py()
        self.assertIn('traffic_cut=True', src)
        self.assertIn('if not ics_mode and traffic_cut:', src)

    def test_apply_percent_cut_uses_mitm_only_kill(self) -> None:
        src = self._killer_py()
        block = src[src.index('def apply_percent_cut'): src.index('def disable_percent_cut', src.index('def apply_percent_cut'))]
        self.assertIn('traffic_cut=False', block)
        self.assertIn('return False', block)
        self.assertIn('return bool(fw', block)

    def test_toggle_percent_cut_stops_when_backend_still_active(self) -> None:
        src = self._main_py()
        toggle = src[src.index('def togglePercentCut'): src.index('def stopPercentCut', src.index('def togglePercentCut'))]
        self.assertIn('_percent_cut_backend_active', toggle)
        self.assertIn('stopPercentCut(log=True)', toggle)

    def test_stop_percent_cut_uses_fast_unkill(self) -> None:
        src = self._main_py()
        stop = src[src.index('def stopPercentCut'): src.index('def _refresh_advanced_lag_mitm_if_visible', src.index('def stopPercentCut'))]
        self.assertIn('_release_pctcut_victim_immediate', stop)
        self.assertIn('_percent_cut_ui_shows_on', src[src.index('def _updatePercentCutButtonState'): src.index('def _refresh_flow_toggle_ui', src.index('def _updatePercentCutButtonState'))])

    def test_forwarder_percent_pass_is_stochastic(self) -> None:
        from networking.forwarder import MitmForwarder

        fw = MitmForwarder(debug=False)
        passes = sum(1 for _ in range(500) if fw._passes_ratio(50, 'out', 1400))
        self.assertGreater(passes, 150)
        self.assertLess(passes, 350)


if __name__ == '__main__':
    unittest.main()
