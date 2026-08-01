"""PC Wi-Fi link diagnostic (Logs → Wi-Fi link)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tools import support_wifi_link_diag as wld  # noqa: E402

_SAMPLE = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6E AX211
    GUID                   : 12345678-1234-1234-1234-1234567890ab
    Physical address       : aa-bb-cc-dd-ee-ff
    State                  : connected
    SSID                   : HomeLan
    BSSID                  : 11:22:33:44:55:66
    Network type           : Infrastructure
    Radio type             : 802.11ax
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Connection mode        : Auto Connect
    Channel                : 44
    Receive rate (Mbps)    : 1201
    Transmit rate (Mbps)   : 1201
    Signal                 : 88%
    Profile                : HomeLan
"""


class TestWifiLinkParse(unittest.TestCase):
    def test_parse_connected_5ghz_wpa2(self) -> None:
        adapters = wld.parse_wlan_interfaces(_SAMPLE)
        self.assertEqual(len(adapters), 1)
        a = adapters[0]
        self.assertTrue(a['connected'])
        self.assertEqual(a['ssid'], 'HomeLan')
        self.assertEqual(a['authentication'], 'WPA2-Personal')
        self.assertEqual(a['cipher'], 'CCMP')
        self.assertEqual(a['channel'], 44)
        self.assertEqual(a['band'], '5 GHz')
        self.assertIn('802.11ax', a['radio_type'])

    def test_band_from_channel(self) -> None:
        self.assertEqual(wld.band_from_channel(6), '2.4 GHz')
        self.assertEqual(wld.band_from_channel(36), '5 GHz')
        self.assertEqual(wld.band_from_channel(149), '5 GHz')
        self.assertEqual(wld.band_from_channel(200), '6 GHz')

    def test_prefers_explicit_band_field(self) -> None:
        text = """
    Name                   : Wi-Fi
    State                  : connected
    SSID                   : Mesh6
    Authentication         : WPA3-Personal
    Cipher                 : GCMP-256
    Channel                : 37
    Band                   : 6 GHz
"""
        a = wld.parse_wlan_interfaces(text)[0]
        self.assertEqual(a['band'], '6 GHz')
        self.assertEqual(a['authentication'], 'WPA3-Personal')

    def test_report_mentions_pc_only(self) -> None:
        adapters = wld.parse_wlan_interfaces(_SAMPLE)
        text = wld.format_wifi_link_report(adapters)
        self.assertIn('this PC only', text)
        self.assertIn('SCREENSHOT THIS SUMMARY', text)
        self.assertIn('5 GHz', text)
        self.assertIn('WPA2-Personal', text)
        self.assertIn('HomeLan', text)
        self.assertNotIn('victim IP', text.lower())

    def test_run_writes_report_without_notepad(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            desk = Path(tmp) / 'Desktop'
            desk.mkdir()
            with (
                mock.patch.object(sys, 'platform', 'win32'),
                mock.patch.object(wld, '_desktop_dir', return_value=desk),
                mock.patch.object(wld, '_run_netsh_wlan_interfaces', return_value=_SAMPLE),
                mock.patch.object(wld, '_open_notepad') as open_np,
            ):
                ok, msg, path = wld.run_wifi_link_diag(open_report=True)
            self.assertTrue(ok)
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.is_file())
            self.assertIn('HomeLan', msg)
            self.assertIn('5 GHz', msg)
            self.assertIn('WPA2-Personal', path.read_text(encoding='utf-8'))
            open_np.assert_called_once()

    def test_non_windows(self) -> None:
        with mock.patch.object(sys, 'platform', 'linux'):
            ok, msg, path = wld.run_wifi_link_diag()
        self.assertFalse(ok)
        self.assertIsNone(path)
        self.assertIn('Windows-only', msg)


class TestLogsWifiButton(unittest.TestCase):
    def test_logs_window_has_wifi_link_button(self) -> None:
        path = os.path.join(_SRC, 'gui', 'logs_window.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn("setObjectName('logsDiagWifiBtn')", src)
        self.assertIn('Wi-Fi link', src)
        self.assertIn('def _run_wifi_link_check', src)
        self.assertIn('launch_wifi_link_diag', src)
        # Still PC-only — no victim band probe wiring.
        self.assertNotIn('victim band', src.lower())

    def test_wifi_button_shares_charcoal_theme(self) -> None:
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('QPushButton#logsDiagWifiBtn', src)
        start = src.index('QFrame#logsDiagPanel')
        end = src.index('QPushButton#logsDiagWifiBtn:pressed')
        block = src[start:end]
        self.assertNotIn('#19232D', block)
        self.assertNotIn('#1A72BB', block)


if __name__ == '__main__':
    unittest.main()
