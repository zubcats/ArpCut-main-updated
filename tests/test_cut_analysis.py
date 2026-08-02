"""Deep cut Analysis scoring and Logs Analysis toggle wiring."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _gui_source import load_main_window_source, method_src


def _live_host(**extra):
    from tools import cut_analysis as ca

    base = dict(
        iface_name='Wi-Fi',
        iface_ip='192.168.1.26',
        gateway_mac='11:22:33:44:55:66',
        settings_adapter_live=True,
        ip_forwarding_on=False,
        l2_ready=True,
        victim_ping_ok=True,
        victim_in_arp=True,
        victim_mac_match=True,
        victim_on_lan=True,
        selected_victim_ip='192.168.1.50',
        selected_victim_mac='aa:bb:cc:dd:ee:ff',
    )
    base.update(extra)
    return ca.collect_host_health(**base)


def _sample(
    ipv4=8,
    arp_victim=1,
    ipv6=0,
    poison_arp_seen=0,
    victim_to_us=0,
    victim_wan_out_to_us=0,
    victim_wan_bypass_gw=0,
    wan_return_bypass=0,
    victim_lan_ipv4=0,
):
    return {
        'ok': True,
        'error': '',
        'ipv4': ipv4,
        'ipv6': ipv6,
        'arp': max(1, arp_victim),
        'arp_victim': arp_victim,
        'poison_arp_seen': poison_arp_seen,
        'victim_to_us': victim_to_us,
        'victim_wan_out_to_us': victim_wan_out_to_us,
        'victim_wan_bypass_gw': victim_wan_bypass_gw,
        'wan_return_bypass': wan_return_bypass,
        'victim_lan_ipv4': victim_lan_ipv4,
        'total': ipv4 + ipv6 + 2,
        'seconds': 2.0,
    }


class TestLanWanHelpers(unittest.TestCase):
    def test_wan_vs_lan_classification(self) -> None:
        from tools.cut_analysis import _is_lan_ipv4, _is_wan_ipv4

        self.assertTrue(_is_lan_ipv4('192.168.1.50'))
        self.assertTrue(_is_lan_ipv4('10.0.0.2'))
        self.assertTrue(_is_lan_ipv4('172.16.5.1'))
        self.assertFalse(_is_wan_ipv4('192.168.1.50'))
        self.assertTrue(_is_wan_ipv4('1.1.1.1'))
        self.assertTrue(_is_wan_ipv4('8.8.8.8'))


class TestCutAnalysisScoring(unittest.TestCase):
    def test_success_full_cut_all_phases_pass(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host()
        before = ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(), host=host)
        during = ca.PhaseSample(
            phase=ca.PHASE_DURING,
            sample=_sample(
                ipv4=12,
                victim_wan_out_to_us=10,
                victim_to_us=12,
                victim_wan_bypass_gw=0,
                wan_return_bypass=0,
            ),
            host=host,
            stack=ca.collect_stack_state(
                mitm_armed=True,
                forwarder_running=True,
                forwarder_hard_drop=True,
                fwd_packets_seen=20,
                fwd_packets_dropped=20,
                fwd_packets_forwarded=0,
                sample_window_ok=True,
            ),
        )
        after = ca.PhaseSample(
            phase=ca.PHASE_AFTER,
            sample=_sample(ipv4=2, arp_victim=0),
            host=host,
            stack=ca.collect_stack_state(
                mitm_armed=False,
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
        self.assertEqual(report.verdict, 'FULL CUT')
        self.assertEqual(report.overall, 'SUCCESS')
        blob = '\n'.join(report.lines)
        self.assertIn('OVERALL RESULT:  SUCCESS', blob)
        self.assertIn('BEFORE  >>>  PASS', blob)
        self.assertIn('DURING  >>>  PASS', blob)
        self.assertIn('AFTER  >>>  PASS', blob)
        self.assertIn('THIS SECTION: PASSED', blob)
        self.assertIn('FULL CUT DEEP DIVE (victim path)', blob)
        self.assertIn('victim connection FULLY SEVERED', blob)
        self.assertIn('Victim WAN path severed', blob)
        self.assertIn('not ZubCut blocking its own view', blob)

    def test_wan_bypass_is_partial_fail_even_if_stack_armed(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host()
        report = ca.score_phases(
            flow='Kill',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=True,
            before=ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(), host=host),
            during=ca.PhaseSample(
                phase=ca.PHASE_DURING,
                sample=_sample(
                    ipv4=10,
                    victim_wan_out_to_us=0,
                    victim_wan_bypass_gw=8,
                    wan_return_bypass=2,
                ),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=True,
                    forwarder_running=True,
                    forwarder_hard_drop=True,
                    fwd_packets_seen=0,
                    fwd_packets_dropped=0,
                    sample_window_ok=True,
                ),
            ),
            after=ca.PhaseSample(
                phase=ca.PHASE_AFTER,
                sample=_sample(ipv4=0),
                host=host,
                stack=ca.collect_stack_state(mitm_armed=False, forwarder_running=False),
            ),
        )
        self.assertEqual(report.verdict, 'PARTIAL')
        self.assertEqual(report.overall, 'FAIL')
        blob = '\n'.join(report.lines)
        self.assertIn('NOT severed', blob)
        self.assertIn('bypass', blob.lower())

    def test_poison_arp_alone_is_not_victim_severance(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host()
        report = ca.score_phases(
            flow='Kill',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=True,
            before=ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(ipv4=0), host=host),
            during=ca.PhaseSample(
                phase=ca.PHASE_DURING,
                sample=_sample(
                    ipv4=0,
                    arp_victim=2,
                    poison_arp_seen=5,
                    victim_wan_out_to_us=0,
                    victim_to_us=0,
                ),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=True,
                    forwarder_running=True,
                    forwarder_hard_drop=True,
                    fwd_packets_seen=0,
                    fwd_packets_dropped=0,
                    sample_window_ok=True,
                ),
            ),
            after=ca.PhaseSample(
                phase=ca.PHASE_AFTER,
                sample=_sample(ipv4=0),
                host=host,
                stack=ca.collect_stack_state(mitm_armed=False, forwarder_running=False),
            ),
        )
        self.assertEqual(report.verdict, 'INCONCLUSIVE')
        self.assertEqual(report.overall, 'FAIL')
        self.assertIn('poison ARP alone', '\n'.join(report.lines))

    def test_armed_without_evidence_is_inconclusive_fail(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host()
        report = ca.score_phases(
            flow='Kill',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=True,
            before=ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(ipv4=0), host=host),
            during=ca.PhaseSample(
                phase=ca.PHASE_DURING,
                sample=_sample(ipv4=0, arp_victim=0),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=True,
                    forwarder_running=True,
                    forwarder_hard_drop=True,
                    fwd_packets_seen=0,
                    fwd_packets_dropped=0,
                    fwd_packets_forwarded=0,
                    sample_window_ok=True,
                ),
            ),
            after=ca.PhaseSample(
                phase=ca.PHASE_AFTER,
                sample=_sample(ipv4=0),
                host=host,
                stack=ca.collect_stack_state(mitm_armed=False, forwarder_running=False),
            ),
        )
        self.assertEqual(report.verdict, 'INCONCLUSIVE')
        self.assertEqual(report.overall, 'FAIL')
        self.assertIn('not proven severed', '\n'.join(report.lines).lower())

    def test_missed_sample_window_fails(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host()
        report = ca.score_phases(
            flow='Dupe',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=True,
            before=ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(), host=host),
            during=ca.PhaseSample(
                phase=ca.PHASE_DURING,
                sample=_sample(ipv4=0, arp_victim=0),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=False,
                    forwarder_running=False,
                    forwarder_hard_drop=False,
                    sample_window_ok=False,
                ),
            ),
            after=ca.PhaseSample(
                phase=ca.PHASE_AFTER,
                sample=_sample(ipv4=0),
                host=host,
                stack=ca.collect_stack_state(mitm_armed=False, forwarder_running=False),
            ),
        )
        self.assertEqual(report.overall, 'FAIL')
        blob = '\n'.join(report.lines)
        self.assertIn('8000 ms', blob)
        self.assertIn('already turned OFF', blob)

    def test_forwarder_missing_is_fail_partial(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host()
        report = ca.score_phases(
            flow='Kill',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=True,
            before=ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(), host=host),
            during=ca.PhaseSample(
                phase=ca.PHASE_DURING,
                sample=_sample(),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=True,
                    forwarder_running=False,
                    forwarder_hard_drop=False,
                ),
            ),
            after=ca.PhaseSample(
                phase=ca.PHASE_AFTER,
                sample=_sample(ipv4=0, arp_victim=0),
                host=host,
                stack=ca.collect_stack_state(mitm_armed=False, forwarder_running=False),
            ),
        )
        self.assertEqual(report.verdict, 'PARTIAL')
        self.assertEqual(report.overall, 'FAIL')
        blob = '\n'.join(report.lines)
        self.assertIn('OVERALL RESULT:  FAIL', blob)
        self.assertIn('DURING  >>>  FAIL', blob)
        self.assertIn('THIS SECTION: FAILED', blob)
        self.assertIn('NOT proven severed', blob)
        self.assertIn('forwarder', blob.lower())

    def test_stale_offline_victim_is_fail(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host(
            victim_ping_ok=False,
            victim_in_arp=False,
            victim_mac_match=False,
            victim_on_lan=False,
            victim_live_ip='192.168.1.165',
            victim_liveness_note=(
                '192.168.1.248 is offline — this device is now at 192.168.1.165. '
                'Rescan and use that row.'
            ),
            selected_victim_ip='192.168.1.248',
        )
        report = ca.score_phases(
            flow='Dupe',
            victim_ip='192.168.1.248',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=True,
            before=ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(ipv4=0), host=host),
            during=ca.PhaseSample(
                phase=ca.PHASE_DURING,
                sample=_sample(ipv4=0, arp_victim=0),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=True,
                    forwarder_running=True,
                    forwarder_hard_drop=True,
                ),
            ),
            after=ca.PhaseSample(
                phase=ca.PHASE_AFTER,
                sample=_sample(ipv4=0, arp_victim=0),
                host=host,
                stack=ca.collect_stack_state(mitm_armed=False, forwarder_running=False),
            ),
        )
        self.assertEqual(report.verdict, 'NOT CUT')
        self.assertEqual(report.overall, 'FAIL')
        blob = '\n'.join(report.lines)
        self.assertIn('OVERALL RESULT:  FAIL', blob)
        self.assertIn('BEFORE  >>>  FAIL', blob)
        self.assertIn('192.168.1.165', blob)

    def test_after_mitm_still_armed_fails_overall(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host()
        report = ca.score_phases(
            flow='Dupe',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=True,
            before=ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(), host=host),
            during=ca.PhaseSample(
                phase=ca.PHASE_DURING,
                sample=_sample(ipv4=10),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=True,
                    forwarder_running=True,
                    forwarder_hard_drop=True,
                ),
            ),
            after=ca.PhaseSample(
                phase=ca.PHASE_AFTER,
                sample=_sample(ipv4=0, arp_victim=0),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=True,
                    forwarder_running=False,
                    forwarder_hard_drop=False,
                ),
            ),
        )
        self.assertEqual(report.overall, 'FAIL')
        self.assertIn('AFTER  >>>  FAIL', '\n'.join(report.lines))
        self.assertIn('still armed', '\n'.join(report.lines).lower())

    def test_percent_cut_success_without_full_cut(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host()
        report = ca.score_phases(
            flow='Percent Cut',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=False,
            cut_pct=40,
            before=ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(), host=host),
            during=ca.PhaseSample(
                phase=ca.PHASE_DURING,
                sample=_sample(),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=True,
                    forwarder_running=True,
                    forwarder_hard_drop=False,
                    cut_pct=40,
                ),
            ),
            after=ca.PhaseSample(
                phase=ca.PHASE_AFTER,
                sample=_sample(ipv4=1),
                host=host,
                stack=ca.collect_stack_state(mitm_armed=False, forwarder_running=False),
            ),
        )
        self.assertEqual(report.overall, 'SUCCESS')
        self.assertIn('OVERALL RESULT:  SUCCESS', '\n'.join(report.lines))

    def test_ip_forwarding_on_is_partial_fail(self) -> None:
        from tools import cut_analysis as ca

        host = _live_host(ip_forwarding_on=True)
        report = ca.score_phases(
            flow='Kill',
            victim_ip='192.168.1.50',
            victim_mac='aa:bb:cc:dd:ee:ff',
            expect_full_cut=True,
            before=ca.PhaseSample(phase=ca.PHASE_BEFORE, sample=_sample(), host=_live_host()),
            during=ca.PhaseSample(
                phase=ca.PHASE_DURING,
                sample=_sample(),
                host=host,
                stack=ca.collect_stack_state(
                    mitm_armed=True,
                    forwarder_running=True,
                    forwarder_hard_drop=True,
                ),
            ),
            after=ca.PhaseSample(
                phase=ca.PHASE_AFTER,
                sample=_sample(ipv4=0),
                host=_live_host(),
                stack=ca.collect_stack_state(mitm_armed=False, forwarder_running=False),
            ),
        )
        self.assertEqual(report.verdict, 'PARTIAL')
        self.assertEqual(report.overall, 'FAIL')


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

    def test_single_final_report_requires_all_phases(self) -> None:
        src = load_main_window_source()
        self.assertNotIn('def _emit_cut_analysis_interim', src)
        finalize = method_src('_finalize_cut_analysis_session')
        self.assertIn("live.get('before') is None", finalize)
        self.assertIn("live.get('during') is None", finalize)
        self.assertIn("live.get('after') is None", finalize)
        self.assertIn('save_cut_analysis_report(report, open_report=True)', finalize)
        self.assertIn('report_saved', finalize)
        after = method_src('_schedule_cut_analysis_after_off')
        self.assertIn("sess.get('report_saved')", after)
        during = method_src('_schedule_cut_analysis_if_enabled')
        self.assertNotIn('save_cut_analysis_report', during)

    def test_flows_begin_before_instant_cut(self) -> None:
        kill = method_src('toggleKill')
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
        self.assertIn('8000 ms', src)
        self.assertIn('8s', src)
        self.assertIn('5000 ms', src)  # still warns that 5s is often too short

    def test_save_report_uses_zubcut_diagnostics_folder(self) -> None:
        from tools import cut_analysis as ca
        from tools import diag_paths as dp
        from tools.diag_paths import DIAGNOSTICS_FOLDER_NAME

        report = ca.CutAnalysisReport(
            flow='Dupe',
            verdict='FULL CUT',
            overall='SUCCESS',
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
