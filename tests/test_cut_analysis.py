"""Deep cut Analysis scoring and Logs Analysis toggle wiring."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _gui_source import load_main_window_source, method_src


class TestCutAnalysisScoring(unittest.TestCase):
    def test_full_cut_when_mitm_hard_drop_forwarding_off(self) -> None:
        from tools import cut_analysis as ca

        with mock.patch.object(
            ca,
            '_sniff_cut_sample',
            return_value={
                'ok': True,
                'error': '',
                'ipv4': 12,
                'ipv6': 0,
                'arp': 2,
                'arp_poison_like': 1,
                'total': 15,
            },
        ):
            report = ca.analyze_victim_cut(
                flow='Dupe',
                victim_ip='192.168.1.50',
                victim_mac='aa:bb:cc:dd:ee:ff',
                iface_guid='guid',
                iface_name='Wi-Fi',
                expect_full_cut=True,
                mitm_armed=True,
                forwarder_running=True,
                forwarder_hard_drop=True,
                ip_forwarding_on=False,
            )
        self.assertEqual(report.verdict, 'FULL CUT')
        self.assertIn('FULL CUT', report.summary_line)

    def test_partial_when_forwarder_missing(self) -> None:
        from tools import cut_analysis as ca

        with mock.patch.object(
            ca,
            '_sniff_cut_sample',
            return_value={
                'ok': True,
                'error': '',
                'ipv4': 3,
                'ipv6': 0,
                'arp': 1,
                'arp_poison_like': 1,
                'total': 4,
            },
        ):
            report = ca.analyze_victim_cut(
                flow='Kill',
                victim_ip='192.168.1.50',
                victim_mac='aa:bb:cc:dd:ee:ff',
                iface_guid='guid',
                expect_full_cut=True,
                mitm_armed=True,
                forwarder_running=False,
                forwarder_hard_drop=False,
                ip_forwarding_on=False,
            )
        self.assertEqual(report.verdict, 'PARTIAL')
        self.assertTrue(any('forwarder' in ln.lower() for ln in report.lines))

    def test_not_cut_when_mitm_not_armed(self) -> None:
        from tools import cut_analysis as ca

        with mock.patch.object(
            ca,
            '_sniff_cut_sample',
            return_value={
                'ok': True,
                'error': '',
                'ipv4': 0,
                'ipv6': 0,
                'arp': 0,
                'arp_poison_like': 0,
                'total': 0,
            },
        ):
            report = ca.analyze_victim_cut(
                flow='Kill',
                victim_ip='192.168.1.50',
                victim_mac='aa:bb:cc:dd:ee:ff',
                iface_guid='guid',
                expect_full_cut=True,
                mitm_armed=False,
            )
        self.assertEqual(report.verdict, 'NOT CUT')

    def test_percent_cut_is_not_full_offline(self) -> None:
        from tools import cut_analysis as ca

        with mock.patch.object(
            ca,
            '_sniff_cut_sample',
            return_value={
                'ok': True,
                'error': '',
                'ipv4': 5,
                'ipv6': 0,
                'arp': 0,
                'arp_poison_like': 0,
                'total': 5,
            },
        ):
            report = ca.analyze_victim_cut(
                flow='Percent Cut',
                victim_ip='192.168.1.50',
                victim_mac='aa:bb:cc:dd:ee:ff',
                iface_guid='guid',
                expect_full_cut=False,
                cut_pct=40,
                mitm_armed=True,
                forwarder_running=True,
                forwarder_hard_drop=False,
            )
        self.assertEqual(report.verdict, 'PARTIAL')
        self.assertNotEqual(report.verdict, 'FULL CUT')


class TestCutAnalysisWiring(unittest.TestCase):
    def test_schedule_helper_and_toggle_api(self) -> None:
        src = load_main_window_source()
        self.assertIn('def cut_analysis_enabled', src)
        self.assertIn('def set_cut_analysis_enabled', src)
        self.assertIn('def _schedule_cut_analysis_if_enabled', src)
        self.assertIn('def _run_cut_analysis_now', src)
        sched = method_src('_schedule_cut_analysis_if_enabled')
        self.assertIn('cut_analysis_enabled', sched)
        self.assertIn('zubcut-cut-analysis', sched)
        # Must yield before work (instant cut first).
        self.assertIn('sleep(', sched)

    def test_mitm_probe_schedules_analysis(self) -> None:
        probe = method_src('_schedule_mitm_traffic_probe')
        self.assertIn('_schedule_cut_analysis_if_enabled', probe)

    def test_logs_analysis_toggle(self) -> None:
        path = os.path.join(_SRC, 'gui', 'logs_window.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn("setObjectName('logsDiagAnalysisBtn')", src)
        self.assertIn("QPushButton('Analysis'", src)
        self.assertIn('setCheckable(True)', src)
        self.assertIn('_on_analysis_toggled', src)
        self.assertIn('set_cut_analysis_enabled', src)

    def test_analysis_button_qss_no_qdark_blue(self) -> None:
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('logsDiagAnalysisBtn', src)
        self.assertIn('logsDiagAnalysisBtn:checked', src)
        block = src[src.index('logsDiagAnalysisBtn'): src.index('logsDiagAnalysisBtn:checked:hover')]
        self.assertNotIn('#19232D', block)
        self.assertNotIn('#1A72BB', block)


if __name__ == '__main__':
    unittest.main()
