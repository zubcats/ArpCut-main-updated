"""ZubCut status/logging: single lblleft strip + Dupe inline label."""
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


class TestDupeStatusLogging(unittest.TestCase):
    def _main_py(self) -> str:
        return load_main_window_source()

    def test_log_documents_single_status_strip(self) -> None:
        src = self._main_py()
        log_doc = methods_through('log', '_append_log_history')
        self.assertIn('lblleft', log_doc)
        self.assertIn('right-click the status line', log_doc.lower())

    def test_dupe_uses_visible_inline_status(self) -> None:
        src = self._main_py()
        self.assertIn('def _show_dupe_status', src)
        self.assertIn('def _log_dupe_restore_result', src)
        start = methods_through('startDupe', 'dupe_remaining_ms')
        self.assertIn('_show_dupe_status', start)
        stop = methods_through('stopDupe', '_updateDupeButtonState')
        self.assertIn('_log_dupe_restore_result', stop)
        self.assertIn('def _schedule_dupe_arm_command', src)
        self.assertIn('def _run_dupe_arm_command', src)
        self.assertIn('_schedule_dupe_arm_command(device, direction, dupe_gen)', src)
        self.assertIn('Arming…', src)
        self.assertIn('plan.is_ics_downstream', src)
        self.assertIn('Hotspot target resolved', src)
        self.assertIn('def _prepare_ics_victim_context', src)
        self.assertIn('def _retry_ics_windivert_capture', src)
        self.assertNotIn(
            'killer.killed',
            src[src.index('def _dupe_arm_watchdog'): src.index('QTimer.singleShot(400, _dupe_arm_watchdog)', src.index('def _dupe_arm_watchdog'))],
        )
        self.assertIn('Dupe arming MITM', src)
        self.assertIn('def _arm_victim_mitm_like_kill', src)
        self.assertIn('traffic_cut=True', methods_through('_arm_victim_mitm_like_kill', '_arm_dupe_mitm_like_kill'))
        self.assertIn('_clear_explicit_kill_for_flow', src)
        self.assertIn('from_button: bool = False', src)
        self.assertIn('_shortcut_global_dupe(from_button=True)', src)
        self.assertIn('_shortcut_global_lag(from_button=True)', src)
        lag_def = methods_through('_lag_deferred_start', '_lag_reassert_poison')
        self.assertIn('_resolve_flow_start_device', src)
        self.assertIn("_arm_victim_mitm_like_kill(", lag_def)
        self.assertIn("flow='Lag'", lag_def)
        mitm = methods_through('_log_mitm_arm_status', '_ensure_network_context_for_victim')
        self.assertIn('UI_LOG_VICTIM_BLOCK_FG', mitm)
        self.assertNotIn("'gray'", mitm)

    def test_startup_teardown_does_not_set_shutting_down(self) -> None:
        src = self._main_py()
        cancel = methods_through('_cancel_deferred_flow_starts', '_teardown_all_attacks')
        self.assertNotIn('_shutting_down = True', cancel)
        self.assertIn('def quit_all', src)
        quit_body = methods_through('quit_all', 'showEvent')
        self.assertIn('_shutting_down = True', quit_body)
        self.assertNotIn('_arm_dupe_burst_wall_clock()', methods_through('_run_dupe_arm_command', '_apply_dupe_deferred'))
        start = methods_through('startDupe', 'dupe_remaining_ms')
        self.assertIn('_arm_dupe_burst_wall_clock()', start)


if __name__ == '__main__':
    unittest.main()
