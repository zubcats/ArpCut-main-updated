"""Unit tests for tools.readiness (PC + device path; no Kill-path I/O)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.readiness import (
    ReadinessFinding,
    collect_device_path_readiness,
    collect_pc_readiness,
    iface_looks_virtual,
    ipv4_same_subnet,
    worst_level,
)


class TestReadinessHelpers(unittest.TestCase):
    def test_ipv4_same_subnet(self):
        self.assertTrue(ipv4_same_subnet('192.168.1.10', '192.168.1.50', 24))
        self.assertFalse(ipv4_same_subnet('192.168.1.10', '192.168.2.50', 24))
        self.assertFalse(ipv4_same_subnet('bad', '192.168.1.1', 24))

    def test_iface_looks_virtual(self):
        self.assertTrue(iface_looks_virtual('NordLynx', ''))
        self.assertTrue(iface_looks_virtual('vEthernet (Default Switch)', ''))
        self.assertFalse(iface_looks_virtual('Wi-Fi', '{guid}'))

    def test_worst_level(self):
        rows = [
            ReadinessFinding('ok', 'fine'),
            ReadinessFinding('warn', 'hmm', code='ZC-WPA3'),
            ReadinessFinding('fail', 'nope', code='ZC-NPCAP'),
        ]
        self.assertEqual(worst_level(rows), 'fail')
        self.assertEqual(worst_level(rows[:2]), 'warn')


class TestCollectPcReadiness(unittest.TestCase):
    @patch('tools.readiness.count_default_routes_ipv4', return_value=1)
    @patch('tools.readiness.hvci_memory_integrity_enabled', return_value=False)
    @patch('tools.readiness.ip_forwarding_registry_on', return_value=False)
    @patch('tools.utils_gui.ensure_npcap_service_running', return_value=True)
    @patch('tools.utils_gui.npcap_admin_only_enabled', return_value=False)
    @patch('tools.utils_gui.npcap_exists', return_value=True)
    def test_pc_ok_admin_clean(self, *_mocks):
        findings = collect_pc_readiness(
            is_admin=True,
            iface_name='Wi-Fi',
            iface_guid='{abc}',
            iface_ip='192.168.1.20',
        )
        self.assertEqual(findings, [])

    @patch('tools.readiness.count_default_routes_ipv4', return_value=1)
    @patch('tools.readiness.hvci_memory_integrity_enabled', return_value=False)
    @patch('tools.readiness.ip_forwarding_registry_on', return_value=False)
    @patch('tools.utils_gui.ensure_npcap_service_running', return_value=True)
    @patch('tools.utils_gui.npcap_admin_only_enabled', return_value=False)
    @patch('tools.utils_gui.npcap_exists', return_value=True)
    def test_pc_fail_not_admin(self, *_mocks):
        findings = collect_pc_readiness(
            is_admin=False,
            iface_name='Wi-Fi',
            iface_ip='192.168.1.20',
        )
        codes = {f.code for f in findings}
        self.assertIn('ZC-ADMIN', codes)

    @patch('tools.readiness.count_default_routes_ipv4', return_value=3)
    @patch('tools.readiness.hvci_memory_integrity_enabled', return_value=True)
    @patch('tools.readiness.ip_forwarding_registry_on', return_value=False)
    @patch('tools.utils_gui.ensure_npcap_service_running', return_value=True)
    @patch('tools.utils_gui.npcap_admin_only_enabled', return_value=False)
    @patch('tools.utils_gui.npcap_exists', return_value=True)
    def test_pc_warn_vpn_hvci_routes(self, *_mocks):
        findings = collect_pc_readiness(
            is_admin=True,
            iface_name='WireGuard Tunnel',
            iface_ip='10.0.0.2',
        )
        codes = {f.code for f in findings}
        self.assertIn('ZC-ROUTE', codes)
        self.assertIn('ZC-WD-HVCI', codes)


class TestCollectDevicePathReadiness(unittest.TestCase):
    def test_ok_path(self):
        findings = collect_device_path_readiness(
            {'ip': '192.168.1.50', 'mac': 'aa:bb:cc:dd:ee:ff', 'name': 'PS5'},
            iface_ip='192.168.1.20',
            router_ip='192.168.1.1',
            router_mac='11:22:33:44:55:66',
            wifi_link_hints=[],
            lan_ipv6_enabled=False,
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, 'ok')
        self.assertIn('PS5', findings[0].message)

    def test_missing_macs_and_subnet(self):
        findings = collect_device_path_readiness(
            {'ip': '10.0.0.5', 'mac': '', 'name': 'X'},
            iface_ip='192.168.1.20',
            router_ip='192.168.1.1',
            router_mac='',
            wifi_link_hints=['ZC-WPA3'],
            lan_ipv6_enabled=True,
        )
        codes = {f.code for f in findings}
        self.assertIn('ZC-VMAC', codes)
        self.assertIn('ZC-GWMAC', codes)
        self.assertIn('ZC-ROUTE', codes)
        self.assertIn('ZC-WPA3', codes)
        self.assertIn('ZC-IPV6', codes)
        self.assertNotEqual(worst_level(findings), 'ok')

    def test_skips_admin_row(self):
        findings = collect_device_path_readiness(
            {'ip': '192.168.1.1', 'mac': 'aa:bb:cc:dd:ee:ff', 'admin': True},
            iface_ip='192.168.1.20',
            router_ip='192.168.1.1',
            router_mac='11:22:33:44:55:66',
        )
        self.assertEqual(findings, [])


class TestDeviceCheckOnceSemantics(unittest.TestCase):
    """Mirror GUI cache: first IP per scan only."""

    def test_set_marks_ip_once(self):
        checked: set[str] = set()
        ip = '192.168.1.50'
        key = ip.lower()
        self.assertNotIn(key, checked)
        checked.add(key)
        self.assertIn(key, checked)
        # Second click would no-op
        self.assertTrue(key in checked)


if __name__ == '__main__':
    unittest.main()
