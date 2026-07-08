"""Lag must pause hotspot traffic on click; heavy ICS prep runs at startup/wake."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestLagInstantPreblock(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_instant_preblock_helper_exists(self) -> None:
        src = self._main_py()
        self.assertIn('def _lag_instant_preblock', src)
        self.assertIn('def _flow_instant_preblock', src)
        flow = src[src.index('def _flow_instant_preblock'): src.index('def _lag_instant_preblock')]
        self.assertIn('IcsWinDivertLagGate(ip)', flow)

    def test_lag_preblocks_before_deferred(self) -> None:
        src = self._main_py()
        start = src[
            src.index('def startLagSwitch'): src.index('QTimer.singleShot(0, _lag_deferred_start)')
        ]
        self.assertIn('_lag_instant_preblock(snap)', start)
        pre = start.index('_lag_instant_preblock')
        deferred = start.index('self._lag_start_gen')
        self.assertLess(pre, deferred)

    def test_impairment_warmup_hooks(self) -> None:
        src = self._main_py()
        self.assertIn('def _warm_impairment_stack', src)
        self.assertIn('def _ics_stack_is_warm', src)
        self.assertIn("_schedule_impairment_stack_warm('startup')", src)
        self.assertIn("_schedule_impairment_stack_warm('post_scan')", src)
        self.assertIn('_on_app_state_for_impairment_warm', src)

    def test_ics_context_skips_bind_when_warm(self) -> None:
        src = self._main_py()
        ctx = src[src.index('def _prepare_ics_victim_context'): src.index('def _prepare_victim_for_impairment')]
        self.assertIn('_ics_stack_is_warm()', ctx)
        self.assertIn('if not warm:', ctx)

    def test_deferred_ics_skips_full_arm_when_preblocked(self) -> None:
        src = self._main_py()
        deferred = src[
            src.index('def _lag_deferred_start'): src.index('def _lag_abort_start')
        ]
        self.assertIn('_lag_ics_preblocked', deferred)
        self.assertIn('plan.use_windivert', deferred)
        self.assertIn('_apply_ics_client_block', deferred)
        self.assertIn("flow='Lag'", deferred)
        ics_arm = deferred[deferred.index('if plan.use_windivert:'): deferred.index('else:')]
        self.assertNotIn('_arm_victim_mitm_like_kill', ics_arm)

    def test_lan_warmup_helpers_exist(self) -> None:
        src = self._main_py()
        self.assertIn('def _warm_lan_mitm_stack', src)
        self.assertIn('def _lan_mitm_stack_is_warm', src)
        warm = src[src.index('def _warm_impairment_stack'): src.index('def _start_impairment_warm_on_reactivate')]
        self.assertIn('_warm_lan_mitm_stack()', warm)

    def test_unified_flow_preblock_helper(self) -> None:
        src = self._main_py()
        self.assertIn('def _flow_instant_preblock', src)

    def test_instant_preblock_covers_lan_arp(self) -> None:
        src = self._main_py()
        pre = src[src.index('def _flow_instant_preblock'): src.index('def _lag_instant_preblock')]
        self.assertIn('plan.use_arp_mitm', pre)
        self.assertIn('killer.kill(dev, wait_after=0.0, traffic_cut=True)', pre)
        self.assertNotIn('elif self._lan_mitm_stack_is_warm():', pre)

    def test_lag_starts_block_phase_on_preblock(self) -> None:
        src = self._main_py()
        start = src[
            src.index('def startLagSwitch'): src.index('QTimer.singleShot(0, _lag_deferred_start)')
        ]
        self.assertIn('_lag_phase_begin_block(dict(snap))', start)

    def test_kill_clear_skips_unkill_when_lag_lan_preblocked(self) -> None:
        src = self._main_py()
        clear_fn = src[
            src.index('def _clear_explicit_kill_for_flow')
            : src.index('def _clear_explicit_kill_for_dupe')
        ]
        self.assertIn('_lag_lan_preblocked', clear_fn)
        self.assertIn('_dupe_preblocked', clear_fn)

    def test_warmup_on_device_select(self) -> None:
        src = self._main_py()
        clicked = src[src.index('def deviceClicked'): src.index('def _updateLagSwitchButtonState')]
        self.assertIn("_schedule_impairment_stack_warm('select')", clicked)

    def test_kill_preblocks_before_schedule(self) -> None:
        src = self._main_py()
        toggle = src[src.index('def toggleKill'): src.index('def _percent_cut_backend_active')]
        self.assertIn("_flow_instant_preblock(dev, 'both', flow='Kill')", toggle)
        pre = toggle.index('_flow_instant_preblock')
        sched = toggle.index('_schedule_kill_command')
        self.assertLess(pre, sched)

    def test_dupe_preblocks_before_deferred(self) -> None:
        src = self._main_py()
        start = src[
            src.index('def startDupe'): src.index('QTimer.singleShot(0, _dupe_deferred_start)')
        ]
        self.assertIn("_flow_instant_preblock(device, direction, flow='Dupe')", start)

    def test_deferred_lan_skips_full_arm_when_preblocked(self) -> None:
        src = self._main_py()
        deferred = src[
            src.index('def _lag_deferred_start'): src.index('def _lag_abort_start')
        ]
        self.assertIn('_lag_lan_preblocked', deferred)
        self.assertIn('_lan_mitm_stack_is_warm()', deferred)
        lan_arm = deferred[deferred.index('else:'): deferred.index('_clear_explicit_kill_for_flow')]
        self.assertIn('if lan_preblocked:', lan_arm)
        self.assertIn('reassert_poison', lan_arm)

    def test_ensure_gate_fast_path_before_prep(self) -> None:
        src = self._main_py()
        gate_fn = src[src.index('def _ensure_ics_lag_gate'): src.index('def _apply_ics_client_block')]
        prep_idx = gate_fn.index('_prepare_victim_for_impairment')
        fast_idx = gate_fn.index('ip_quick')
        self.assertLess(fast_idx, prep_idx)


if __name__ == '__main__':
    unittest.main()
