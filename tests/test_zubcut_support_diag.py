"""Tests for tools/zubcut_support_diag.py"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
_TOOLS = _ROOT / 'tools'
# Put tools/ on path for the diag script, then src/ ahead of it so `tools.utils`
# resolves to src/tools (not the scripts folder namespace collision).
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_SRC) in sys.path:
    sys.path.remove(str(_SRC))
sys.path.insert(0, str(_SRC))

import zubcut_support_diag as diag  # noqa: E402


class TestParseIpconfig(unittest.TestCase):
    def test_extracts_wifi_ipv4(self) -> None:
        text = """
Wireless LAN adapter Wi-Fi:

   Connection-specific DNS Suffix  . :
   IPv4 Address. . . . . . . . . . . : 192.168.1.56
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
"""
        adapters = diag.parse_ipconfig_windows(text)
        self.assertEqual(len(adapters), 1)
        self.assertIn('Wi-Fi', adapters[0]['name'])
        self.assertEqual(adapters[0]['ipv4'], '192.168.1.56')


class TestFormatReport(unittest.TestCase):
    def test_includes_header_and_issues(self) -> None:
        report = {
            'timestamp_utc': '2026-01-01T00:00:00Z',
            'platform': 'win32',
            'python': '3.11',
            'admin': False,
            'tool_version': 2,
            'frozen': False,
            'sections': {
                'application': {},
                'settings': {},
                'os_network': {'adapters': []},
                'adapters': {},
                'mitm': {},
                'npcap': {},
                'capture_probe': {},
                'clumsy': {},
                'windivert': {},
            },
            'issues': [{'severity': 'warn', 'code': 'not_admin', 'message': 'Run as admin'}],
            'recommendations': ['Run elevated'],
            'summary_lines': ['[FAIL] Running as Administrator'],
        }
        text = diag.format_text_report(report)
        self.assertIn('ZubCut Support Diagnostic', text)
        self.assertIn('SCREENSHOT THIS SUMMARY', text)
        self.assertIn('not_admin', text)
        self.assertIn('Run elevated', text)
        self.assertIn('Clumsy / Hotspot', text)


class TestSummaryBuilder(unittest.TestCase):
    def test_summary_mentions_admin_and_npcap(self) -> None:
        report = {
            'admin': True,
            'issues': [],
            'sections': {
                'npcap': {'installed': True, 'winpcap': {'uninstall_key_present': False}, 'related_programs': []},
                'mitm': {'gateway_ip': '192.168.1.1', 'gateway_mac': 'aa:bb:cc:dd:ee:ff', 'ip_forwarding_enabled': False},
                'capture_probe': {'skipped': True},
                'clumsy': {'mode_enabled': False, 'hotspot_137_visible': False},
                'windivert': {'any_complete': False},
                'victims': [],
            },
        }
        rows = diag._build_summary_lines(report)
        joined = '\n'.join(rows)
        self.assertIn('[PASS] Running as Administrator', joined)
        self.assertIn('[PASS] Npcap installed', joined)
        self.assertIn('[PASS] WinPcap/Win10Pcap absent', joined)


class TestWriteReports(unittest.TestCase):
    def test_writes_txt_and_json(self) -> None:
        report = {'tool': 'zubcut_support_diag', 'issues': [], 'sections': {}, 'recommendations': []}
        with tempfile.TemporaryDirectory() as tmp:
            txt, js = diag.write_reports(report, Path(tmp), 'test-diag')
            self.assertTrue(txt.is_file())
            self.assertTrue(js.is_file())
            loaded = json.loads(js.read_text(encoding='utf-8'))
            self.assertEqual(loaded['tool'], 'zubcut_support_diag')


class TestCollectReportSmoke(unittest.TestCase):
    def test_collect_returns_expected_keys(self) -> None:
        # Avoid importing real scapy-heavy modules; stub the pieces collect_report needs.
        fake_utils = mock.MagicMock()
        fake_utils.get_ifaces.return_value = []
        fake_utils.pick_best_live_iface.return_value = None
        fake_utils_gui = mock.MagicMock()
        fake_utils_gui.import_settings_as_dict.return_value = {
            'iface': '',
            'clumsy_mode': False,
        }
        fake_utils_gui.npcap_exists.return_value = False
        with mock.patch.dict(
            sys.modules,
            {
                'tools.utils': fake_utils,
                'tools.utils_gui': fake_utils_gui,
            },
        ):
            report = diag.collect_report(skip_capture=True)
        self.assertEqual(report['tool'], 'zubcut_support_diag')
        self.assertEqual(report.get('tool_version'), diag.TOOL_VERSION)
        self.assertIn('sections', report)
        self.assertIn('issues', report)
        self.assertIn('summary_lines', report)
        self.assertIn('clumsy', report['sections'])
        self.assertIn('windivert', report['sections'])


if __name__ == '__main__':
    unittest.main()
