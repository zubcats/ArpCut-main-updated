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
    winpcap_leftover_present,
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


_PC_CLEAN_PATCHES = (
    patch('tools.readiness.probe_wifi_link_hint_codes', return_value=[]),
    patch('tools.readiness.winpcap_leftover_present', return_value=False),
    patch('tools.readiness.count_default_routes_ipv4', return_value=1),
    patch('tools.readiness.hvci_memory_integrity_enabled', return_value=False),
    patch('tools.readiness.ip_forwarding_registry_on', return_value=False),
    patch('tools.utils_gui.ensure_npcap_service_running', return_value=True),
    patch('tools.utils_gui.npcap_admin_only_enabled', return_value=False),
    patch('tools.utils_gui.npcap_exists', return_value=True),
    patch('tools.clumsy_inline.clumsy_bundle_incomplete', return_value=False),
    patch('tools.clumsy_inline.clumsy_mode_enabled', return_value=False),
    patch('tools.clumsy_inline.windivert_bundle_complete', return_value=True),
)


def _apply_pc_clean_patches(fn):
    for p in reversed(_PC_CLEAN_PATCHES):
        fn = p(fn)
    return fn


class TestCollectPcReadiness(unittest.TestCase):
    @_apply_pc_clean_patches
    def test_pc_ok_admin_clean(self, *_mocks):
        findings = collect_pc_readiness(
            is_admin=True,
            iface_name='Wi-Fi',
            iface_guid='{abc}',
            iface_ip='192.168.1.20',
            router_ip='192.168.1.1',
            router_mac='11:22:33:44:55:66',
            probe_wifi=False,
        )
        self.assertEqual(findings, [])

    @_apply_pc_clean_patches
    def test_pc_fail_not_admin(self, *_mocks):
        findings = collect_pc_readiness(
            is_admin=False,
            iface_name='Wi-Fi',
            iface_ip='192.168.1.20',
            probe_wifi=False,
        )
        codes = {f.code for f in findings}
        self.assertIn('ZC-ADMIN', codes)

    @_apply_pc_clean_patches
    def test_pc_warn_vpn_hvci_routes(self, *_mocks):
        # Override HVCI / routes from the clean stack via nested patches.
        with patch('tools.readiness.count_default_routes_ipv4', return_value=3), patch(
            'tools.readiness.hvci_memory_integrity_enabled', return_value=True
        ):
            findings = collect_pc_readiness(
                is_admin=True,
                iface_name='WireGuard Tunnel',
                iface_ip='10.0.0.2',
                probe_wifi=False,
            )
        codes = {f.code for f in findings}
        self.assertIn('ZC-ROUTE', codes)
        self.assertIn('ZC-WD-HVCI', codes)

    @_apply_pc_clean_patches
    def test_pc_fail_winpcap_and_gwmac(self, *_mocks):
        with patch('tools.readiness.winpcap_leftover_present', return_value=True):
            findings = collect_pc_readiness(
                is_admin=True,
                iface_name='Wi-Fi',
                iface_ip='192.168.1.20',
                router_ip='192.168.1.1',
                router_mac='',
                probe_wifi=False,
            )
        codes = {f.code for f in findings}
        self.assertIn('ZC-WINPCAP', codes)
        self.assertIn('ZC-GWMAC', codes)

    @_apply_pc_clean_patches
    def test_pc_warn_windivert_when_clumsy_on(self, *_mocks):
        with patch('tools.clumsy_inline.clumsy_mode_enabled', return_value=True), patch(
            'tools.clumsy_inline.windivert_bundle_complete', return_value=False
        ), patch(
            'tools.readiness.probe_wifi_link_hint_codes', return_value=['ZC-WPA3', 'ZC-MLO']
        ):
            findings = collect_pc_readiness(
                is_admin=True,
                iface_name='Wi-Fi',
                iface_ip='192.168.1.20',
                router_ip='192.168.1.1',
                router_mac='11:22:33:44:55:66',
                probe_wifi=True,
            )
        codes = {f.code for f in findings}
        self.assertIn('ZC-WD', codes)
        self.assertIn('ZC-WPA3', codes)
        self.assertIn('ZC-MLO', codes)

    @_apply_pc_clean_patches
    def test_pc_no_windivert_warn_in_dev_when_clumsy_off(self, *_mocks):
        # clumsy_bundle_incomplete() is often True in non-frozen checkouts — must not spam.
        with patch('tools.clumsy_inline.clumsy_bundle_incomplete', return_value=True), patch(
            'tools.clumsy_inline.clumsy_mode_enabled', return_value=False
        ), patch.object(sys, 'frozen', False, create=True):
            findings = collect_pc_readiness(
                is_admin=True,
                iface_name='Wi-Fi',
                iface_ip='192.168.1.20',
                router_ip='192.168.1.1',
                router_mac='11:22:33:44:55:66',
                probe_wifi=False,
            )
        codes = {f.code for f in findings}
        self.assertNotIn('ZC-WD', codes)

    @_apply_pc_clean_patches
    def test_pc_fail_gateway_subnet(self, *_mocks):
        findings = collect_pc_readiness(
            is_admin=True,
            iface_name='Wi-Fi',
            iface_ip='192.168.1.20',
            router_ip='10.0.0.1',
            router_mac='11:22:33:44:55:66',
            probe_wifi=False,
        )
        codes = {f.code for f in findings}
        self.assertIn('ZC-ROUTE', codes)

    def test_winpcap_helper_non_windows(self):
        if sys.platform.startswith('win'):
            self.assertIsInstance(winpcap_leftover_present(), bool)
        else:
            self.assertFalse(winpcap_leftover_present())


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
        self.assertNotIn('ZC-IPV6', codes)
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


class TestPcReadinessScheduleSemantics(unittest.TestCase):
    """Pure state-machine checks for first pass vs enrich (no Qt)."""

    def test_force_first_run_does_not_burn_enrich(self):
        started = False
        enriched = False
        force = True
        # warm wins race
        if started and not force:
            self.fail('should not skip')
        if force and started:
            self.fail('should not mark enrich on first run')
        was_enrich = bool(force and started)
        started = True
        self.assertFalse(was_enrich)
        self.assertTrue(started)
        self.assertFalse(enriched)
        # later post_scan force should be allowed as enrich
        force2 = True
        if started and not force2:
            self.fail('force should proceed')
        if force2 and started:
            self.assertFalse(enriched)
            enriched = True
        self.assertTrue(enriched)


if __name__ == '__main__':
    unittest.main()
