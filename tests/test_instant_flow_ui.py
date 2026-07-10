"""Flow toggles must paint optimistic UI before network / teardown work."""
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


class TestInstantFlowUi(unittest.TestCase):
    def _main_py(self) -> str:
        return load_main_window_source()

    def test_paint_helpers_exist(self) -> None:
        src = self._main_py()
        self.assertIn('def _paint_flow_start_ui', src)
        self.assertIn('def _repaint_device_table_rows', src)
        self.assertIn('def _flush_gui_events', src)

    def test_lag_paints_before_deferred_arm(self) -> None:
        src = self._main_py()
        start = src[
            src.index('def startLagSwitch'): src.index("self._paint_flow_start_ui('lag', device)")
        ]
        self.assertIn('_sync_lag_timing_values_from_ui', start)
        self.assertIn("btnLagSwitch.setText('■ LAGGING')", start)
        self.assertNotIn('_refresh_lag_timing_from_dialog()', start)

    def test_dupe_paints_before_deferred_arm(self) -> None:
        src = self._main_py()
        full = methods_through('startDupe', 'dupe_remaining_ms')
        paint_at = full.index("self._paint_flow_start_ui('dupe', device)")
        deferred_at = full.index('QTimer.singleShot(0, _dupe_deferred_start)')
        self.assertLess(paint_at, deferred_at)
        # Optimistic button/status chrome must appear before paint helper / deferred arm.
        self.assertLess(full.index("btnDupe.setText('■ DUPE')"), paint_at)

    def test_percent_cut_paints_before_crossflow_teardown(self) -> None:
        src = self._main_py()
        toggle = src[
            src.index('def togglePercentCut'): src.index("self._paint_flow_start_ui('pctcut', device)")
        ]
        self.assertNotIn('_await_mitm_teardown_thread', toggle)
        self.assertNotIn('stopLagSwitch', toggle)

    def test_kill_paints_before_schedule(self) -> None:
        src = self._main_py()
        toggle = method_src('toggleKill')
        paint = toggle.index('_paint_flow_start_ui')
        schedule = toggle.index('_schedule_kill_command')
        self.assertLess(paint, schedule)
        self.assertNotIn('clumsy_ics_lag_can_use_windivert', toggle)

    def test_kill_button_fast_mode_skips_plan_lookup(self) -> None:
        src = self._main_py()
        fn = method_src('_updateKillButtonState')
        fast_branch = fn[fn.index('fast: bool'): fn.index('is_active = self._kill_ui_shows_on')]
        self.assertIn('not fast', fast_branch)
        self.assertIn('_impairment_plan_for', fast_branch)

    def test_advanced_lag_optimistic_before_deferred(self) -> None:
        src = self._main_py()
        start = methods_through('start_mitm_shaping_from_advanced', '_await_mitm_teardown_thread')
        optimistic = start.index('self.mitm_shaping_active = True')
        deferred = start.index('QTimer.singleShot(0, _deferred_start)')
        self.assertLess(optimistic, deferred)


    def test_lag_block_apply_deferred(self) -> None:
        src = self._main_py()
        block = methods_through('_lag_phase_begin_block', '_lag_phase_begin_allow')
        self.assertIn('_lag_apply_block(cur)', block)
        self.assertNotIn('QTimer.singleShot(0, _lag_block_apply)', block)

    def test_lag_arming_countdown_on_click(self) -> None:
        src = self._main_py()
        start = src[
            src.index('def startLagSwitch'): src.index('QTimer.singleShot(0, _lag_deferred_start)')
        ]
        self.assertIn('_lag_phase_arming = True', start)
        self.assertIn("Arming…", start)
        self.assertIn('_lag_countdown_timer.start()', start)
        deferred = methods_through('_lag_deferred_start', '_lag_abort_start')
        self.assertNotIn('_await_mitm_teardown_thread', deferred)
        self.assertIn('_clear_explicit_kill_for_flow', deferred)
        self.assertIn('plan.use_windivert', deferred)
        self.assertIn('_lag_instant_preblock', methods_through('startLagSwitch', '_lag_abort_start'))

    def test_dupe_finish_deferred(self) -> None:
        src = self._main_py()
        self.assertIn('def _dupe_finish_from_countdown_sync', src)
        finish = methods_through('_dupe_finish_from_countdown', 'stopDupe')
        self.assertIn('QTimer.singleShot(0', finish)

    def test_dupe_wall_clock_starts_on_click(self) -> None:
        src = self._main_py()
        start = src[
            src.index('def startDupe'): src.index('QTimer.singleShot(0, _dupe_deferred_start)')
        ]
        self.assertIn('_arm_dupe_burst_wall_clock()', start)


if __name__ == '__main__':
    unittest.main()
