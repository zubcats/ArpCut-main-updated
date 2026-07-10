"""Lag Switch on ICS must not use Kill bookkeeping (killer.killed / killed_devices)."""
from __future__ import annotations

import inspect
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


class TestLagSwitchIcsBookkeeping(unittest.TestCase):
    def _main_py(self) -> str:
        return load_main_window_source()

    def test_apply_ics_client_block_supports_for_lag(self) -> None:
        src = self._main_py()
        self.assertIn('for_lag: bool = False', src)

    def test_apply_ics_client_block_skips_kill_state_for_lag(self) -> None:
        src = self._main_py()
        block = methods_through('_apply_ics_client_block', '_clear_ics_client_block')
        self.assertIn('for_lag: bool = False', block)
        self.assertIn('_ics_kill_profile_macs.add', block)
        self.assertRegex(
            block,
            r'elif for_lag:\s*\n\s*self\._refresh_table_row_for_mac',
        )
        self.assertNotIn('release_ics_victim_block', block)

    def test_lag_apply_block_prefers_fast_windivert_pause(self) -> None:
        src = self._main_py()
        block = methods_through('_lag_apply_block', '_lag_resolved_victim')
        self.assertIn('_lag_ics_set_paused(device, True)', block)
        self.assertIn('_apply_ics_client_block', block)
        self.assertIn('for_lag=True', block)

    def test_row_chrome_respects_allow_phase(self) -> None:
        src = self._main_py()
        self.assertIn('_lag_in_allow_phase', src)

    def test_lag_uses_single_shot_phase_timer(self) -> None:
        src = self._main_py()
        self.assertIn('_lag_phase_end_timer_fired', src)
        fired = methods_through('_lag_phase_end_timer_fired', '_lag_do_phase_advance')
        self.assertIn('_lag_do_phase_advance', fired)

    def test_stop_lag_switch_does_not_use_removed_lag_timer(self) -> None:
        src = self._main_py()
        stop = methods_through('stopLagSwitch', 'startDupe')
        self.assertNotIn('lag_timer', stop)

    def test_stop_lag_switch_releases_instantly_like_dupe(self) -> None:
        src = self._main_py()
        stop = methods_through('stopLagSwitch', 'startDupe')
        self.assertIn('_ics_emergency_release', stop)
        self.assertIn('_cancel_lag_block_reassert', stop)
        self.assertNotIn('QTimer.singleShot(0, _lag_teardown)', stop)
        self.assertNotIn('_schedule_flow_off_reinforce', stop)

    def test_stop_dupe_restores_arp_before_firewall_drain(self) -> None:
        src = self._main_py()
        stop = methods_through('stopDupe', '_updateDupeButtonState')
        self.assertIn('_release_dupe_victim_immediate', stop)
        self.assertIn('_resolve_dupe_stop_snapshot', stop)
        release_fn = methods_through('_release_dupe_victim_immediate', '_apply_victim_block')
        self.assertIn('_release_victim_arp_mitm_stack(device', release_fn)
        self.assertNotIn('_drain_dupe_block_if_needed', stop)
        apply_def = methods_through('_apply_dupe_deferred', '_slot_finish_dupe_block')
        self.assertIn('_run_dupe_arm_command', apply_def)
        deferred = methods_through('_do_deferred_dupe_clear', '_arm_dupe_burst_wall_clock')
        self.assertNotIn('_clear_victim_block', deferred)
        self.assertNotIn('killer.unkill', deferred)

    def test_lag_allow_phase_uses_fast_windivert_resume(self) -> None:
        src = self._main_py()
        resume = methods_through('_lag_ics_resume_allow_phase', '_lag_apply_allow_phase_sync')
        self.assertTrue(
            '_ics_gate_allow_traffic' in resume or 'clear_blocking_pause' in resume,
            'allow phase must resume WinDivert in-place',
        )
        self.assertNotIn('_ics_hotspot_pause_release', resume)
        self.assertNotIn('_lag_ics_force_unpause', resume)
        allow = methods_through('_lag_phase_begin_allow', '_lag_apply_block')
        self.assertIn('_lag_ics_set_paused(cur, False)', allow)
        self.assertIn('_lag_apply_allow_phase_sync', allow)
        self.assertIn('_sync_lag_timing_values_from_ui', allow)
        self.assertNotIn('_refresh_lag_timing_from_dialog', allow)
        self.assertNotIn('_schedule_lag_start_reassert', allow)
        block = methods_through('_lag_phase_begin_block', '_lag_phase_begin_allow')
        self.assertIn('_sync_lag_timing_values_from_ui', block)
        self.assertNotIn('_refresh_lag_timing_from_dialog', block)
        self.assertNotIn('_cancel_lag_block_reassert', block)
        start = src[src.index('def _lag_deferred_start'): src.index('QTimer.singleShot(0, _lag_deferred_start)')]
        self.assertIn('_lag_phase_begin_block', start)
        self.assertIn('_schedule_lag_start_reassert', start)
        tick = methods_through('_tick_lag_countdown', '_lag_phase_begin_block')
        self.assertNotIn('_lag_ics_force_unpause', tick)
        self.assertTrue(
            '_lag_do_phase_advance(force=True)' in tick or '_lag_request_phase_advance()' in tick,
            'countdown expiry must advance the lag phase',
        )

    def test_lag_warm_mitm_skips_unkill_between_phases(self) -> None:
        src = self._main_py()
        self.assertIn('def _lag_lan_mitm_warm', src)
        self.assertIn('def _lag_apply_block_warm', src)
        allow = methods_through('_lag_ics_resume_allow_phase', '_lag_apply_allow_phase_sync')
        self.assertIn('_lag_clear_block_only', allow)
        block = methods_through('_lag_apply_block', '_lag_resolved_victim')
        self.assertIn('_lag_apply_block_warm', block)
        self.assertIn('_lag_lan_mitm_warm', block)

    def test_release_windivert_unpauses_without_gate_match(self) -> None:
        src = self._main_py()
        rel = methods_through('_release_ics_windivert_block', '_schedule_ics_hotspot_heal')
        self.assertNotIn('self._ics_gate_matches_device(device)', rel)


if __name__ == '__main__':
    unittest.main()
