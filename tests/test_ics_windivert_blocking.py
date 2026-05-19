"""ICS WinDivert blocking-mode packet handling."""
from __future__ import annotations

import inspect
import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import ics_windivert_shaper as wd


class TestIcsWinDivertBlocking(unittest.TestCase):
    def test_percent_loss_does_not_drop_allowed_packets_twice(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        block = src[src.index('if blocking:'): src.index('if pass_cut and')]
        self.assertIn('_send_immediate', block)
        self.assertNotRegex(
            block,
            r'elif loss_pct > 0:\s*\n\s*continue',
        )

    def test_percent_cut_uses_byte_budget_not_pause_hold(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate)
        self.assertIn('def apply_percent_cut', src)
        self.assertIn('_passes_byte_ratio', src)
        self.assertIn('if pass_cut and', inspect.getsource(wd.IcsWinDivertLagGate._run_loop))
        apply = src[src.index('def apply_percent_cut'): src.index('def apply_shaping_params')]
        self.assertIn('self._blocking = False', apply)
        self.assertIn('self._pass_cut_active = True', apply)

    def test_apply_shaping_clears_blocking_and_percent_cut(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate.apply_shaping_params)
        self.assertIn('self._blocking = False', src)
        self.assertIn('_clear_percent_cut_unlocked', src)
        self.assertIn('self._discard_heap = True', src)

    def test_clear_blocking_pause_leaves_partial_modes_ready(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate.clear_blocking_pause)
        self.assertIn('self._blocking = False', src)
        self.assertIn('self._hold_pause = False', src)
        self.assertIn('self._discard_heap = True', src)

    def test_hotspot_percent_cut_uses_windivert_helper(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('def _ics_apply_percent_cut_windivert', src)
        self.assertIn('def _ics_apply_advanced_shaping_windivert', src)
        toggle = src[src.index('def togglePercentCut'): src.index('def stopPercentCut')]
        self.assertIn('clumsy_ics_use_firewall_only(device, self.scanner)', toggle)
        self.assertIn('_ics_apply_percent_cut_windivert(device, pct)', toggle)

    def test_passes_byte_ratio_matches_forwarder_semantics(self) -> None:
        budget = 0.0
        allowed = 0
        for _ in range(200):
            ok, budget = wd.IcsWinDivertLagGate._passes_byte_ratio(99, budget, 100)
            if ok:
                allowed += 1
        self.assertGreater(allowed, 150)
        self.assertLess(allowed, 200)
        ok2, _ = wd.IcsWinDivertLagGate._passes_byte_ratio(1, 0.0, 1000)
        self.assertFalse(ok2)


if __name__ == '__main__':
    unittest.main()
