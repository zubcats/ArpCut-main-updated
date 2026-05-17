"""Clumsy ICS: hotspot mode must not tear down Mobile Hotspot."""

from __future__ import annotations

import inspect
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import clumsy_ics as ics


class ClumsyHotspotSafetyTests(unittest.TestCase):
    def test_enable_script_hotspot_enables_ics_when_no_dhcp(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn("$ZubcutTopology = '{topo}'", src)
        self.assertIn('Get-NetUDPEndpoint -LocalPort 67', src)
        self.assertIn('Hotspot UI can be On without DHCP', src)
        hotspot_idx = src.index("if ($ZubcutTopology -eq 'hotspot')")
        netsh_idx = src.index('netsh wlan stop hostednetwork', hotspot_idx)
        self.assertGreater(netsh_idx, hotspot_idx)

    def test_repair_does_not_demote_wlansvc_to_manual(self) -> None:
        src = inspect.getsource(ics.repair_clumsy_network_sharing)
        self.assertNotIn('Set-Service -Name $svc -StartupType Manual', src)
        self.assertNotIn('Stop-Service -Name $svc', src)
        self.assertIn('Ensure-WlanAutoConfigHealthy', src)
        self.assertIn('Restart-NetworkSharingServicesSafe', src)
        self.assertIn("WlanSvc) is still not running", src)

    def test_repair_preserves_ics_when_hotspot_active(self) -> None:
        src = inspect.getsource(ics.repair_clumsy_network_sharing)
        self.assertIn('$skipIcsReset = $hotspotWasOn', src)
        self.assertIn('Apply-HotspotIcs', src)
        self.assertIn('if (-not $preserveHotspot)', src)

    def test_repair_reenables_mobile_hotspot(self) -> None:
        src = inspect.getsource(ics.repair_clumsy_network_sharing)
        self.assertIn('Ensure-MobileHotspotOn', src)
        self.assertIn('hotspotWasOn', src)
        self.assertIn('hotspotReenabled', src)

    def test_prepare_can_restart_tethering(self) -> None:
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        self.assertIn('Ensure-MobileHotspotOn', src)
        self.assertIn('Restart-SharedAccessSafe', src)

    def test_prepare_automates_sharing_with_hotspot_toggle(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Apply-HotspotIcsAutomated', helpers)
        self.assertIn('Stop-MobileHotspotIfOn', helpers)
        self.assertIn('Apply-HotspotIcsWithTetheringToggle', helpers)
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        self.assertIn('Apply-HotspotIcsAutomated', src)

    def test_prepare_checks_ics_not_only_dhcp(self) -> None:
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        self.assertIn('Test-HotspotIcsActive', src)
        self.assertIn('ics_ok=$false', src)

    def test_enable_script_does_not_set_ics_services_manual(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertNotIn('Set-Service -Name $svc -StartupType Manual', src)

    def test_repair_ps1_script_does_not_demote_wlansvc(self) -> None:
        path = os.path.join(_ROOT, 'tools', 'repair_clumsy_hotspot.ps1')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertNotIn('Set-Service -Name $svc -StartupType Manual', src)
        self.assertNotIn('Stop-Service -Name $svc', src)
        self.assertIn('Ensure-WlanAutoConfigHealthy', src)

    def test_prepare_pc_mobile_hotspot_automation(self) -> None:
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        self.assertIn('ZubCut-DHCP-In', src)
        self.assertIn('needs_manual_sharing', src)
        self.assertNotIn('Stop-Service icssvc', src.replace(' ', ''))

    def test_enable_calls_prepare_for_hotspot(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn('prepare_pc_mobile_hotspot', src)

    def test_format_clumsy_ics_error_not_duplicated(self) -> None:
        raw = 'Turn ON Mobile Hotspot in Windows Settings first.'
        once = ics.format_clumsy_ics_error(raw, topology='hotspot')
        twice = ics.format_clumsy_ics_error(once, topology='hotspot')
        self.assertEqual(once, twice)
        self.assertEqual(once.count('For PS5 → PC Mobile Hotspot'), 1)
        self.assertEqual(once.count('Connect the PS5'), 1)

    def test_startup_heals_wlan_autoconfig(self) -> None:
        zubcut = os.path.join(_SRC, 'zubcut.py')
        with open(zubcut, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('maybe_ensure_wlan_autoconfig_on_startup', src)
        self.assertIn('reset_clumsy_mode_on_startup', src)
        self.assertIn('ensure_wlan_autoconfig_healthy', inspect.getsource(ics))

    def test_reset_clumsy_mode_on_startup_clears_setting(self) -> None:
        from unittest.mock import patch

        with patch('tools.utils_gui.get_settings', return_value=True) as gs, patch(
            'tools.utils_gui.set_settings'
        ) as ss:
            ics.reset_clumsy_mode_on_startup()
        gs.assert_called_once_with('clumsy_mode')
        ss.assert_called_once_with('clumsy_mode', False)

    def test_maybe_repair_skips_when_no_state_file(self) -> None:
        path = ics.clumsy_ics_state_path()
        had = os.path.isfile(path)
        try:
            if had:
                os.remove(path)
            ics.maybe_repair_stale_clumsy_ics_on_startup()
        finally:
            if had and not os.path.isfile(path):
                pass


if __name__ == '__main__':
    unittest.main()
