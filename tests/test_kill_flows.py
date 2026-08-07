"""Kill Flows monitor — verdict logic + UI chrome guards."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.kill_flow_monitor import classify_kill_flow_verdict


class TestKillFlowVerdict(unittest.TestCase):
    def test_waiting_when_kill_off(self):
        v = classify_kill_flow_verdict(
            kill_on=False,
            lan_reachable=True,
            mitm_armed=False,
            ics_path=False,
            out_bps=0,
            in_bps=0,
            saw_any_packets=False,
        )
        self.assertEqual(v.code, 'WAITING')
        self.assertEqual(v.level, 'idle')

    def test_lan_dead(self):
        v = classify_kill_flow_verdict(
            kill_on=True,
            lan_reachable=False,
            mitm_armed=True,
            ics_path=False,
            out_bps=0,
            in_bps=0,
            saw_any_packets=False,
        )
        self.assertEqual(v.code, 'LAN_DEAD')
        self.assertEqual(v.level, 'fail')

    def test_not_armed(self):
        v = classify_kill_flow_verdict(
            kill_on=True,
            lan_reachable=True,
            mitm_armed=False,
            ics_path=False,
            out_bps=0,
            in_bps=0,
            saw_any_packets=False,
        )
        self.assertEqual(v.code, 'NOT_ARMED')

    def test_leaking(self):
        v = classify_kill_flow_verdict(
            kill_on=True,
            lan_reachable=True,
            mitm_armed=True,
            ics_path=False,
            out_bps=100,
            in_bps=5000,
            saw_any_packets=True,
        )
        self.assertEqual(v.code, 'LEAKING')
        self.assertEqual(v.level, 'warn')

    def test_cut_attempts(self):
        v = classify_kill_flow_verdict(
            kill_on=True,
            lan_reachable=True,
            mitm_armed=True,
            ics_path=False,
            out_bps=2000,
            in_bps=50,
            saw_any_packets=True,
        )
        self.assertEqual(v.code, 'CUT_ATTEMPTS')
        self.assertEqual(v.level, 'ok')

    def test_in_path_no_frames(self):
        v = classify_kill_flow_verdict(
            kill_on=True,
            lan_reachable=None,
            mitm_armed=True,
            ics_path=False,
            out_bps=0,
            in_bps=0,
            saw_any_packets=False,
        )
        self.assertEqual(v.code, 'CUT_OR_IDLE')

    def test_arming_while_pending(self):
        v = classify_kill_flow_verdict(
            kill_on=True,
            lan_reachable=True,
            mitm_armed=False,
            ics_path=False,
            out_bps=0,
            in_bps=0,
            saw_any_packets=False,
            kill_pending=True,
        )
        self.assertEqual(v.code, 'ARMING')

    def test_ended_session_keeps_cut_read(self):
        v = classify_kill_flow_verdict(
            kill_on=False,
            lan_reachable=True,
            mitm_armed=False,
            ics_path=False,
            out_bps=0,
            in_bps=0,
            saw_any_packets=True,
            out_bytes=3400,
            in_bytes=0,
            session_had_kill=True,
        )
        self.assertEqual(v.code, 'ENDED_CUT')
        self.assertEqual(v.level, 'ok')

    def test_cut_from_totals_when_rates_zero(self):
        v = classify_kill_flow_verdict(
            kill_on=True,
            lan_reachable=True,
            mitm_armed=True,
            ics_path=False,
            out_bps=0,
            in_bps=0,
            saw_any_packets=True,
            out_bytes=3400,
            in_bytes=0,
        )
        self.assertEqual(v.code, 'CUT_ATTEMPTS')


class TestKillFlowsUiChrome(unittest.TestCase):
    def test_window_uses_auxiliary_object_name(self):
        path = os.path.join(_SRC, 'gui', 'kill_flows.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn("setObjectName('zubcutAuxiliaryWindow')", src)
        self.assertIn("setObjectName('centralwidget')", src)
        self.assertIn("setObjectName('killFlowsTable')", src)
        self.assertNotIn('#19232D', src)
        self.assertNotIn('#1A72BB', src)
        self.assertNotIn('#37414F', src)
        self.assertIn('UI_TABLE_SELECTION_BG', src)
        self.assertIn('ADMIN_DEVICE_TABLE_ROW_BG', src)

    def test_aux_qss_has_kill_flows_selectors(self):
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('QTableWidget#killFlowsTable', src)
        self.assertIn('QFrame#killFlowsStatusRow', src)
        block = src[
            src.index('QTableWidget#killFlowsTable') :
            src.index('QFrame#killFlowsStatusRow') + 80
        ]
        self.assertNotIn('#19232D', block)
        self.assertNotIn('#1A72BB', block)

    def test_main_menu_renamed(self):
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('Kill Flows for Selected', src)
        self.assertIn('openKillFlows', src)
        self.assertNotIn("QAction('Traffic for Selected'", src)

    def test_kill_on_uses_backend_not_only_profile(self):
        path = os.path.join(_SRC, 'gui', 'kill_flows.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        fn = src[src.index('def _kill_on') : src.index('def _mitm_armed')]
        self.assertIn('_explicit_kill_backend_live', fn)
        self.assertIn('_kill_toggle_pending_for_mac', fn)
        self.assertIn('_live_device', fn)

    def test_open_syncs_after_show(self):
        path = os.path.join(_SRC, 'gui', 'kill_flows.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        fn = src[src.index('def open_for_device') : src.index('def notify_kill_state_changed')]
        show_at = fn.index('self.show()')
        sync_at = fn.index('self._sync_sniff_for_state()')
        self.assertLess(show_at, sync_at)
        self.assertIn('self._monitor_open = True', fn)


if __name__ == '__main__':
    unittest.main()
