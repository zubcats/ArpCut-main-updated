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
                'arp_victim': 1,
                'total': 15,
                'seconds': 2.0,
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
                host=ca.collect_host_health(
                    iface_name='Wi-Fi',
                    iface_ip='192.168.1.26',
                    gateway_mac='11:22:33:44:55:66',
                    settings_adapter_live=True,
                    ip_forwarding_on=False,
                ),
            )
        self.assertEqual(report.verdict, 'FULL CUT')
        self.assertIn('BEFORE', '\n'.join(report.lines) + 'DURING')
        self.assertIn('--- DURING ---', '\n'.join(report.lines))

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
                'arp_victim': 1,
                'total': 4,
                'seconds': 2.0,
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
                'arp_victim': 0,
                'total': 0,
                'seconds': 2.0,
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

    def test_after_mitm_still_armed_is_partial(self) -> None:
        from tools import cut_analysis as ca

        before = ca.PhaseSample(
            phase=ca.PHASE_BEFORE,
            sample={
                'ok': True,
                'ipv4': 8,
                'ipv6': 0,
                'arp': 1,
                'arp_victim': 1,
                'total': 9,
                'seconds': 1.2,
            },
            host=ca.collect_host_health(
                iface_name='Wi-Fi',
                iface_ip='192.168.1.26',
                gateway_mac='11:22:33:44:55:66',
                settings_adapter_live=True,
                ip_forwarding_on=False,
            ),
        )
        during = ca.PhaseSample(
            phase=ca.PHASE_DURING,
            sample={
                'ok': True,
                'ipv4': 10,
                'ipv6': 0,
                'arp': 2,
                'arp_victim': 2,
                'total': 12,
                'seconds': 2.0,
            },
            host=before.host,
            stack=ca.collect_stack_state(
                mitm_armed=True,
                forwarder_running=True,
                forwarder_hard_drop=True,
            ),
        )
        after = ca.PhaseSample(
            phase=ca.PHASE_AFTER,
            sample={
                'ok': True,
                'ipv4': 0,
                'ipv6': 0,
                'arp': 0,
                'arp_victim': 0,
                'total': 0,
                'seconds': 1.8,
            },
            host=before.host,
            stack=ca.collect_stack_state(
                mitm_armed=True,
                forwarder_running=False,
                forwarder_hard_drop=False,
            ),
        )
        report = ca.score_phases(
            flow='Dupe',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=True,
            before=before,
            during=during,
            after=after,
        )
        self.assertEqual(report.verdict, 'PARTIAL')
        self.assertTrue(any('AFTER' in r and 'still armed' in r for r in report.lines) or any(
            'still armed' in r for r in report.lines
        ))

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
                'arp_victim': 0,
                'total': 5,
                'seconds': 2.0,
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
        self.assertIn('def _begin_cut_analysis_session', src)
        self.assertIn('def _schedule_cut_analysis_if_enabled', src)
        self.assertIn('def _schedule_cut_analysis_after_off', src)
        self.assertIn('def _refresh_cut_analysis_baseline', src)
        begin = method_src('_begin_cut_analysis_session')
        self.assertIn('BEFORE', begin)
        during = method_src('_schedule_cut_analysis_if_enabled')
        self.assertIn('sleep(', during)
        after = method_src('_schedule_cut_analysis_after_off')
        self.assertIn('PHASE_AFTER', after)

    def test_flows_begin_before_instant_cut(self) -> None:
        kill = method_src('toggleKill')
        # begin must appear before preblock in ON path
        self.assertIn('_begin_cut_analysis_session', kill)
        self.assertLess(
            kill.index('_begin_cut_analysis_session'),
            kill.index("_flow_instant_preblock(dev, 'both', flow='Kill')"),
        )
        dupe = method_src('startDupe')
        self.assertLess(
            dupe.index('_begin_cut_analysis_session'),
            dupe.index("_flow_instant_preblock(device, direction, flow='Dupe')"),
        )
        lag = method_src('startLagSwitch')
        self.assertLess(
            lag.index('_begin_cut_analysis_session'),
            lag.index('_lag_instant_preblock'),
        )

    def test_flows_schedule_after_off(self) -> None:
        self.assertIn('_schedule_cut_analysis_after_off', method_src('stopDupe'))
        self.assertIn('_schedule_cut_analysis_after_off', method_src('stopLagSwitch'))
        self.assertIn('_schedule_cut_analysis_after_off', method_src('stopPercentCut'))
        kill = method_src('_run_kill_command')
        self.assertIn("_schedule_cut_analysis_after_off(victim, flow='Kill')", kill)

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
        self.assertIn('BEFORE', src)
        self.assertIn('DURING', src)
        self.assertIn('AFTER', src)
        self.assertIn('5000 ms', src)
        self.assertIn('5s', src)

    def test_save_report_uses_zubcut_diagnostics_folder(self) -> None:
        import tempfile
        from pathlib import Path

        from tools import cut_analysis as ca
        from tools import diag_paths as dp
        from tools.diag_paths import DIAGNOSTICS_FOLDER_NAME

        report = ca.CutAnalysisReport(
            flow='Dupe',
            verdict='FULL CUT',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            lines=['======== ZubCut Cut Analysis ========', '>>> VERDICT: FULL CUT'],
        )
        fake_dir = Path(tempfile.mkdtemp(prefix='zubcut-analysis-')) / DIAGNOSTICS_FOLDER_NAME

        def _ensure():
            fake_dir.mkdir(parents=True, exist_ok=True)
            return fake_dir

        with mock.patch.object(dp, 'ensure_zubcut_diagnostics_dir', side_effect=_ensure):
            with mock.patch.object(ca, '_open_analysis_report') as open_np:
                path = ca.save_cut_analysis_report(report, open_report=True)
        self.assertIsNotNone(path)
        self.assertEqual(path.parent.name, DIAGNOSTICS_FOLDER_NAME)
        self.assertTrue(str(path.name).startswith('ZubCut-Analysis-'))
        self.assertTrue(path.is_file())
        text = path.read_text(encoding='utf-8')
        self.assertIn('Saved to:', text)
        self.assertIn(DIAGNOSTICS_FOLDER_NAME, text)
        open_np.assert_called_once()

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
