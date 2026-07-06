"""ZubCut status/logging: single lblleft strip + Dupe inline label."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestDupeStatusLogging(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_log_documents_single_status_strip(self) -> None:
        src = self._main_py()
        log_doc = src[src.index('def log(self'): src.index('def _append_log_history', src.index('def log(self'))]
        self.assertIn('lblleft', log_doc)
        self.assertIn('right-click the status line', log_doc.lower())

    def test_dupe_uses_visible_inline_status(self) -> None:
        src = self._main_py()
        self.assertIn('def _show_dupe_status', src)
        self.assertIn('def _log_dupe_restore_result', src)
        start = src[src.index('def startDupe'): src.index('def dupe_remaining_ms', src.index('def startDupe'))]
        self.assertIn('_show_dupe_status', start)
        stop = src[src.index('def stopDupe'): src.index('def _updateDupeButtonState', src.index('def stopDupe'))]
        self.assertIn('_log_dupe_restore_result', stop)
        self.assertIn('def _schedule_dupe_arm_command', src)
        self.assertIn('def _run_dupe_arm_command', src)
        self.assertIn('_schedule_dupe_arm_command(device, direction, dupe_gen)', src)
        self.assertIn('Dupe arming MITM', src)
        self.assertIn('def _arm_victim_mitm_like_kill', src)
        self.assertIn('traffic_cut=True', src[src.index('def _arm_victim_mitm_like_kill'): src.index('def _arm_dupe_mitm_like_kill', src.index('def _arm_victim_mitm_like_kill'))])
        self.assertIn('_clear_explicit_kill_for_flow', src)
        self.assertIn('from_button: bool = False', src)
        self.assertIn('_shortcut_global_dupe(from_button=True)', src)
        self.assertIn('_shortcut_global_lag(from_button=True)', src)
        lag_def = src[src.index('def _lag_deferred_start'): src.index('def _lag_reassert_poison', src.index('def startLagSwitch'))]
        self.assertIn('_resolve_flow_start_device', src)
        self.assertIn('_arm_victim_mitm_like_kill(work_snap, self.lag_direction, flow=\'Lag\')', lag_def)
        mitm = src[src.index('def _log_mitm_arm_status'): src.index('def _ensure_network_context_for_victim', src.index('def _log_mitm_arm_status'))]
        self.assertIn('UI_LOG_VICTIM_BLOCK_FG', mitm)
        self.assertNotIn("'gray'", mitm)


if __name__ == '__main__':
    unittest.main()
