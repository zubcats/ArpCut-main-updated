"""Every impairment entry point must route hotspot victims through ICS prep."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestHotspotIcsPaths(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_unified_prepare_helper_exists(self) -> None:
        src = self._main_py()
        self.assertIn('def _prepare_victim_for_impairment', src)
        body = src[
            src.index('def _prepare_victim_for_impairment')
            : src.index('def _reconcile_network_adapter', src.index('def _prepare_victim_for_impairment'))
        ]
        self.assertIn('plan.is_ics_downstream', body)
        self.assertIn('_prepare_ics_victim_context', body)

    def test_ics_lag_gate_prepares_hotspot(self) -> None:
        src = self._main_py()
        gate = src[src.index('def _ensure_ics_lag_gate'): src.index('def _apply_ics_client_block')]
        self.assertIn('_prepare_victim_for_impairment', gate)

    def test_percent_cut_and_advanced_shaping_prepare_hotspot(self) -> None:
        src = self._main_py()
        pct = src[
            src.index('def _ics_apply_percent_cut_windivert')
            : src.index('def _ics_apply_advanced_shaping_windivert')
        ]
        adv = src[
            src.index('def _ics_apply_advanced_shaping_windivert')
            : src.index('def _ics_hotspot_windivert_teardown')
        ]
        self.assertIn('_prepare_victim_for_impairment', pct)
        self.assertIn('_prepare_victim_for_impairment', adv)

    def test_lag_resolved_victim_skips_lan_resolve_on_hotspot(self) -> None:
        src = self._main_py()
        fn = src[src.index('def _lag_resolved_victim'): src.index('def stopLagSwitch')]
        self.assertIn('plan.is_ics_downstream', fn)
        self.assertIn('_prepare_victim_for_impairment', fn)
        ics_branch = fn[fn.index('plan.is_ics_downstream'): fn.index('resolve_live_lan_victim')]
        self.assertIn('_prepare_victim_for_impairment', ics_branch)
        self.assertNotIn('resolve_live_lan_victim', ics_branch)

    def test_lag_deferred_skips_mitm_prereqs_for_windivert(self) -> None:
        src = self._main_py()
        lag_def = src[
            src.index('def _lag_deferred_start')
            : src.index('def _lag_reassert_poison', src.index('def startLagSwitch'))
        ]
        self.assertIn('_prepare_victim_for_impairment', lag_def)
        self.assertIn('plan.use_windivert', lag_def)
        prereq = lag_def[lag_def.index('mitm_prereqs_ok') - 80: lag_def.index('mitm_prereqs_ok') + 40]
        self.assertIn('not plan.use_windivert', prereq)

    def test_kill_dupe_and_legacy_paths_prepare_hotspot(self) -> None:
        src = self._main_py()
        kill_toggle = src[
            src.index('elif self._uses_windivert(device):', src.index('def toggleKill'))
            : src.index('else:', src.index('elif self._uses_windivert(device):', src.index('def toggleKill')))
        ]
        self.assertIn('_prepare_victim_for_impairment', kill_toggle)
        legacy_kill = src[
            src.index('if self._uses_windivert(device):', src.index('def kill(self'))
            : src.index('else:', src.index('if self._uses_windivert(device):', src.index('def kill(self')))
        ]
        self.assertIn('_prepare_victim_for_impairment', legacy_kill)
        dupe_arm = src[src.index('def _run_dupe_arm_command'): src.index('def _apply_dupe_deferred')]
        self.assertIn('_prepare_victim_for_impairment', dupe_arm)
        ics_block = src[src.index('def _apply_ics_client_block'): src.index('def _clear_ics_client_block')]
        self.assertIn('_prepare_victim_for_impairment', ics_block)


if __name__ == '__main__':
    unittest.main()
