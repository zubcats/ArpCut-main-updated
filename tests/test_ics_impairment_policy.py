"""Device impairment path classification (hotspot vs ethernet vs regular LAN)."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import ics_impairment_policy as policy
from tools import clumsy_inline as inline


class TestIcsImpairmentPolicy(unittest.TestCase):
    def test_regular_when_clumsy_off(self) -> None:
        dev = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.1.50'}
        with mock.patch.object(inline, 'clumsy_mode_enabled', return_value=False):
            plan = policy.classify_device_impairment(dev, None)
        self.assertEqual(plan.path, policy.PATH_REGULAR)
        self.assertTrue(plan.use_arp_mitm)
        self.assertFalse(plan.use_windivert)

    def test_hotspot_client_on_137_subnet(self) -> None:
        dev = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.137.42'}
        with mock.patch.object(inline, 'clumsy_mode_enabled', return_value=True), mock.patch.object(
            inline, 'clumsy_runtime_ready', return_value=True
        ), mock.patch.object(inline, 'windivert_bundle_complete', return_value=True), mock.patch.object(
            inline, 'clumsy_ics_resolve_victim_ip', return_value='192.168.137.42'
        ), mock.patch.object(
            inline, 'victim_on_clumsy_ics_subnet', side_effect=lambda ip: ip.startswith('192.168.137.')
        ), mock.patch.object(
            inline, 'clumsy_ics_downstream_prefix', return_value='192.168.137.'
        ), mock.patch(
            'tools.ics_impairment_policy.read_clumsy_topology', return_value='hotspot'
        ):
            plan = policy.classify_device_impairment(dev, None)
        self.assertEqual(plan.path, policy.PATH_HOTSPOT)
        self.assertTrue(plan.use_windivert)
        self.assertFalse(plan.use_arp_mitm)
        self.assertFalse(plan.use_block_ip)

    def test_ethernet_console_path(self) -> None:
        dev = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.56.10'}
        with mock.patch.object(inline, 'clumsy_mode_enabled', return_value=True), mock.patch.object(
            inline, 'clumsy_runtime_ready', return_value=True
        ), mock.patch.object(inline, 'windivert_bundle_complete', return_value=True), mock.patch.object(
            inline, 'clumsy_ics_resolve_victim_ip', return_value='192.168.56.10'
        ), mock.patch.object(
            inline, 'victim_on_clumsy_ics_subnet', side_effect=lambda ip: ip.startswith('192.168.56.')
        ), mock.patch.object(
            inline, 'clumsy_ics_downstream_prefix', return_value='192.168.56.'
        ), mock.patch(
            'tools.ics_impairment_policy.read_clumsy_topology', return_value='ethernet'
        ):
            plan = policy.classify_device_impairment(dev, None)
        self.assertEqual(plan.path, policy.PATH_ETHERNET)
        self.assertTrue(plan.use_windivert)

    def test_clumsy_inline_firewall_only_delegates_to_policy(self) -> None:
        dev = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.137.2'}
        with mock.patch(
            'tools.ics_impairment_policy.use_windivert_impairment', return_value=True
        ) as m:
            self.assertTrue(inline.clumsy_ics_use_firewall_only(dev, None))
            m.assert_called_once()

    def test_misdetected_ethernet_with_137_gateway_treated_as_hotspot(self) -> None:
        dev = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.137.42'}
        with mock.patch.object(inline, 'clumsy_mode_enabled', return_value=True), mock.patch.object(
            inline, 'clumsy_runtime_ready', return_value=True
        ), mock.patch.object(inline, 'windivert_bundle_complete', return_value=True), mock.patch.object(
            inline, 'clumsy_ics_resolve_victim_ip', return_value='192.168.137.42'
        ), mock.patch.object(
            inline, 'victim_on_clumsy_ics_subnet', side_effect=lambda ip: ip.startswith('192.168.137.')
        ), mock.patch.object(
            inline, 'clumsy_ics_downstream_prefix', return_value='192.168.137.'
        ), mock.patch(
            'tools.ics_impairment_policy.read_clumsy_topology', return_value='ethernet'
        ), mock.patch(
            'tools.clumsy_ics.read_clumsy_ics_state',
            return_value={'downstream_ipv4': '192.168.137.1'},
        ):
            plan = policy.classify_device_impairment(dev, None)
        self.assertEqual(plan.path, policy.PATH_HOTSPOT)
        self.assertEqual(plan.clumsy_topology, 'hotspot')

    def test_hotspot_session_uses_windivert_when_table_shows_home_lan_ip(self) -> None:
        dev = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.1.50'}
        with mock.patch.object(inline, 'clumsy_mode_enabled', return_value=True), mock.patch.object(
            inline, 'clumsy_hotspot_session_active', return_value=True
        ), mock.patch.object(
            inline, 'clumsy_runtime_ready', return_value=True
        ), mock.patch.object(inline, 'windivert_bundle_complete', return_value=True), mock.patch.object(
            inline, 'clumsy_ics_resolve_victim_ip', return_value='192.168.1.50'
        ), mock.patch.object(
            inline, 'clumsy_ics_arp_ip_for_mac', return_value=''
        ), mock.patch.object(
            inline, 'victim_on_clumsy_ics_subnet', return_value=False
        ), mock.patch.object(
            inline, 'clumsy_ics_downstream_prefix', return_value='192.168.137.'
        ), mock.patch(
            'tools.ics_impairment_policy.read_clumsy_topology', return_value='hotspot'
        ):
            plan = policy.classify_device_impairment(dev, None)
        self.assertEqual(plan.path, policy.PATH_HOTSPOT)
        self.assertTrue(plan.use_windivert)
        self.assertTrue(plan.is_ics_downstream)

    def test_main_wires_selection_and_plan_helpers(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('def _refresh_selected_device_impairment_plan', src)
        self.assertIn('def _impairment_plan_for', src)
        self.assertIn('classify_device_impairment', src)
        self.assertIn('_device_with_plan_ip', src)
        block = src[src.index('def _apply_victim_block'): src.index('def _clear_victim_block')]
        self.assertIn('_impairment_plan_for(device)', block)
        self.assertIn('plan.use_windivert', block)
