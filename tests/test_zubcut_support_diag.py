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
_TOOLS = _ROOT / 'tools'
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

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
            'sections': {'application': {}, 'settings': {}, 'os_network': {'adapters': []}, 'adapters': {}, 'mitm': {}, 'npcap': {}, 'capture_probe': {}},
            'issues': [{'severity': 'warn', 'code': 'not_admin', 'message': 'Run as admin'}],
            'recommendations': ['Run elevated'],
        }
        text = diag.format_text_report(report)
        self.assertIn('ZubCut Support Diagnostic', text)
        self.assertIn('not_admin', text)
        self.assertIn('Run elevated', text)


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
        _SRC = _ROOT / 'src'
        if str(_SRC) not in sys.path:
            sys.path.insert(0, str(_SRC))
        with mock.patch('tools.utils.get_ifaces', return_value=[]):
            with mock.patch('tools.utils.pick_best_live_iface', return_value=None):
                with mock.patch('tools.utils_gui.import_settings_as_dict', return_value={'iface': ''}):
                    report = diag.collect_report(skip_capture=True)
        self.assertEqual(report['tool'], 'zubcut_support_diag')
        self.assertIn('sections', report)
        self.assertIn('issues', report)


if __name__ == '__main__':
    unittest.main()
