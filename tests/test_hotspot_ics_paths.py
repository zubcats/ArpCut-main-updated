"""Every impairment entry point must route hotspot victims through ICS prep."""
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


class TestHotspotIcsPaths(unittest.TestCase):
    def _main_py(self) -> str:
        return load_main_window_source()

    def test_unified_prepare_helper_exists(self) -> None:
        src = self._main_py()
        self.assertIn('def _prepare_victim_for_impairment', src)
        body = methods_through('_prepare_victim_for_impairment', '_reconcile_network_adapter')
        self.assertIn('plan.is_ics_downstream', body)
        self.assertIn('_prepare_ics_victim_context', body)

    def test_ics_lag_gate_prepares_hotspot(self) -> None:
        src = self._main_py()
        gate = methods_through('_ensure_ics_lag_gate', '_apply_ics_client_block')
        self.assertIn('_prepare_victim_for_impairment', gate)

    def test_percent_cut_and_advanced_shaping_prepare_hotspot(self) -> None:
        src = self._main_py()
        pct = methods_through('_ics_apply_percent_cut_windivert', '_ics_apply_advanced_shaping_windivert')
        adv = methods_through('_ics_apply_advanced_shaping_windivert', '_ics_hotspot_windivert_teardown')
        self.assertIn('_prepare_victim_for_impairment', pct)
        self.assertIn('_prepare_victim_for_impairment', adv)

    def test_lag_resolved_victim_skips_lan_resolve_on_hotspot(self) -> None:
        src = self._main_py()
        fn = methods_through('_lag_resolved_victim', 'stopLagSwitch')
        self.assertIn('plan.is_ics_downstream', fn)
        self.assertIn('_prepare_victim_for_impairment', fn)
        ics_branch = fn[fn.index('plan.is_ics_downstream'): fn.index('resolve_live_lan_victim')]
        self.assertIn('_prepare_victim_for_impairment', ics_branch)
        self.assertNotIn('resolve_live_lan_victim', ics_branch)

    def test_lag_deferred_skips_mitm_prereqs_for_windivert(self) -> None:
        src = self._main_py()
        lag_def = methods_through('_lag_deferred_start', '_lag_reassert_poison')
        self.assertIn('_prepare_victim_for_impairment', lag_def)
        self.assertIn('plan.use_windivert', lag_def)
        lan_arm = lag_def[lag_def.index('else:'): lag_def.index('_clear_explicit_kill_for_flow')]
        self.assertIn('mitm_prereqs_ok', lan_arm)
        self.assertIn('_arm_victim_mitm_like_kill', lan_arm)
        ics_arm = lag_def[lag_def.index('if plan.use_windivert:'): lag_def.index('else:')]
        self.assertNotIn('mitm_prereqs_ok', ics_arm)

    def test_kill_dupe_and_legacy_paths_prepare_hotspot(self) -> None:
        src = self._main_py()
        kill_toggle = src[
            src.index('elif self._uses_windivert(device):', src.index('def _run_kill_command'))
            : src.index('elif turn_on and mac in self.killer.killed', src.index('def _run_kill_command'))
        ]
        self.assertIn('windivert_instant', kill_toggle)
        self.assertIn('_apply_ics_client_block', kill_toggle)
        toggle_kill = methods_through('toggleKill', '_percent_cut_forwarder_live')
        self.assertIn('_prepare_victim_for_impairment(dev, fast=True)', toggle_kill)
        legacy_kill = src[
            src.index('if self._uses_windivert(device):', src.index('def kill(self'))
            : src.index('else:', src.index('if self._uses_windivert(device):', src.index('def kill(self')))
        ]
        self.assertIn('_prepare_victim_for_impairment', legacy_kill)
        dupe_arm = methods_through('_run_dupe_arm_command', '_apply_dupe_deferred')
        self.assertIn('_prepare_victim_for_impairment', dupe_arm)
        ics_block = methods_through('_apply_ics_client_block', '_clear_ics_client_block')
        self.assertIn('_prepare_victim_for_impairment', ics_block)


if __name__ == '__main__':
    unittest.main()
