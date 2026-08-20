"""Regression: scanner.sync_iface_for_victim_ip must not crash (private utils import)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.ifaces import NetFace
import networking.scanner as scan_mod


def _face(name: str, guid: str, ip: str) -> NetFace:
    return NetFace({"name": name, "guid": guid, "mac": "00:11:22:33:44:55", "ips": [ip]})


class TestScannerSyncIface(unittest.TestCase):
    @patch("networking.scanner.get_gateway_mac", return_value="74:24:9f:e1:4b:6c")
    @patch("networking.scanner.get_gateway_ip", return_value="192.168.1.1")
    @patch("networking.scanner.resolve_iface_my_ip", return_value="192.168.1.56")
    @patch("networking.scanner.get_iface_for_victim_ip")
    def test_sync_iface_for_victim_ip_does_not_raise(
        self, mock_pick, _resolve, _gw_ip, _gw_mac
    ) -> None:
        wifi = _face("Wi-Fi", r"\\Device\\NPF_{WIFI}", "192.168.1.56")
        eth = _face("Ethernet 2", r"\\Device\\NPF_{ETH}", "192.168.1.110")
        mock_pick.return_value = eth

        scanner = scan_mod.Scanner()
        scanner.iface = wifi
        scanner.perfix = "192.168.1"
        scanner.devices = []

        changed = scanner.sync_iface_for_victim_ip("192.168.1.165")
        self.assertTrue(changed)
        self.assertEqual(scanner.iface.name, "Ethernet 2")
        self.assertEqual(scanner.router.get("ip"), "192.168.1.1")

    def test_windows_arp_skips_multicast_when_me_ip_missing(self) -> None:
        scanner = scan_mod.Scanner()
        scanner.my_ip = "0.0.0.0"
        scanner.perfix = "0.0.0"
        text = """
Interface: 192.168.1.56 --- 0x8
  192.168.1.1           74-24-9f-37-1e-ec     dynamic
  192.168.1.160         28-7e-80-0d-01-2c     dynamic
  224.0.0.22            01-00-5e-00-00-16     static
  224.0.0.251           01-00-5e-00-00-fb     static
"""
        hits = scanner._windows_parse_arp_table(text)
        ips = {ip for ip, _mac in hits}
        self.assertIn("192.168.1.160", ips)
        self.assertIn("192.168.1.1", ips)
        self.assertNotIn("224.0.0.22", ips)
        self.assertNotIn("224.0.0.251", ips)

    def test_devices_appender_does_not_reference_undefined_unique(self) -> None:
        import inspect

        src = inspect.getsource(scan_mod.Scanner.devices_appender)
        self.assertNotIn("if unique:", src)
        self.assertNotIn("self.flush_arp()", src)


if __name__ == "__main__":
    unittest.main()
