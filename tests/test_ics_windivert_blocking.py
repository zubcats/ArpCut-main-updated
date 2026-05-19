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
        block = src[
            src.index('if blocking and _packet_involves_victim'): src.index('self._packets_held += 1')
        ]
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

    def test_run_loop_partial_modes_before_blocking_pause(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        block_idx = src.index('if blocking and _packet_involves_victim')
        pass_idx = src.index('if pass_cut and')
        shape_idx = src.index('if shaping and')
        self.assertLess(pass_idx, block_idx)
        self.assertLess(shape_idx, block_idx)

    def test_hotspot_percent_cut_uses_windivert_helper(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('def _ics_apply_percent_cut_windivert', src)
        self.assertIn('def _ics_apply_advanced_shaping_windivert', src)
        toggle = src[src.index('def togglePercentCut'): src.index('def stopPercentCut')]
        self.assertIn('clumsy_ics_use_firewall_only(device, self.scanner)', toggle)
        self.assertIn('_ics_apply_percent_cut_windivert(device, pct)', toggle)
        self.assertIn('def _ics_quiesce_killer_mitm', src)
        self.assertIn('_ics_quiesce_killer_mitm(device)', src)

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

    def test_run_loop_passthrough_non_victim_before_impairment(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        idx = src.index('if not _packet_involves_victim')
        self.assertLess(idx, src.index('if pass_cut and'))
        self.assertLess(idx, src.index('if blocking and _packet_involves_victim'))

    def test_start_opens_subnet_before_victim_handles(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate.start)
        self.assertIn('_open_ics_windivert_handles', src)
        open_src = inspect.getsource(wd._ics_windivert_open_candidates)
        subnet_pos = open_src.find('_ics_windivert_filter')
        victim_pos = open_src.find('_ics_clumsy_victim_filter')
        self.assertLess(subnet_pos, victim_pos)
        best_src = inspect.getsource(wd._open_best_windivert_handle)
        self.assertIn(
            '(WINDIVERT_LAYER_NETWORK_FORWARD, WINDIVERT_LAYER_NETWORK)',
            best_src.replace('\n', ' '),
        )

    def test_hotspot_sched_tick_uses_windivert_on_ics(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        tick = src[src.index('def _mitm_adv_apply_sched_tick'): src.index('def start_mitm_shaping_from_advanced')]
        self.assertIn('clumsy_ics_use_firewall_only(device, self.scanner)', tick)
        self.assertIn('_ics_apply_advanced_shaping_windivert', tick)

    def test_flow_stable_pins_percent_cut_and_mitm_ips(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        fn = src[src.index('def _flow_stable_victim_ip'): src.index('def _ensure_ics_lag_gate')]
        self.assertIn('percent_cut_device_ip', fn)
        self.assertIn('mitm_shaping_device_ip', fn)


if __name__ == '__main__':
    unittest.main()
