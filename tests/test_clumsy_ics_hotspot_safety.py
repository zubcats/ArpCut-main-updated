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
from tools import clumsy_inline as inline


class ClumsyHotspotSafetyTests(unittest.TestCase):
    def test_enable_script_autodetects_console_path(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Detect-ClumsyConsolePath', helpers)
        self.assertIn('Find-EthernetConsoleAdapter', helpers)
        self.assertIn('Get-InternetUplinkAdapter', helpers)
        self.assertIn('Detect-ClumsyConsolePath', src)
        self.assertIn('Get-NetUDPEndpoint -LocalPort 67', src)
        self.assertIn('Apply-InternetSharingForClumsy', src)
        self.assertNotIn('prepare_pc_mobile_hotspot', src)
        hotspot_idx = src.index("if ($ZubcutTopology -eq 'hotspot')")
        netsh_idx = src.index('netsh wlan stop hostednetwork', hotspot_idx)
        self.assertGreater(netsh_idx, hotspot_idx)

    def test_repair_does_not_demote_wlansvc_to_manual(self) -> None:
        src = inspect.getsource(ics.repair_clumsy_network_sharing)
        self.assertNotIn('Set-Service -Name $svc -StartupType Manual', src)
        self.assertNotIn('Stop-Service -Name $svc', src)
        self.assertNotIn("Restart-Service -Name 'WlanSvc'", src)
        self.assertNotIn('Restart-Service -Name WlanSvc', src)
        self.assertIn('Ensure-WlanAutoConfigHealthy', src)
        self.assertIn('Ensure-SharingServicesLight', src)
        self.assertIn("WlanSvc) is still not running", src)

    def test_ensure_wlan_skips_when_already_healthy(self) -> None:
        src = ics._PS_ENSURE_WLAN_HEALTHY
        self.assertIn('return $false', src)
        self.assertIn('Never Stop/Restart WlanSvc', src)

    def test_startup_wlan_heal_only_when_broken(self) -> None:
        src = inspect.getsource(ics.maybe_ensure_wlan_autoconfig_on_startup)
        self.assertIn('_wlan_autoconfig_needs_heal', src)

    def test_repair_preserves_ics_when_hotspot_active(self) -> None:
        src = inspect.getsource(ics.repair_clumsy_network_sharing)
        self.assertIn('$skipIcsReset = $hotspotWasOn', src)
        self.assertIn('Apply-MainWifiSharingForHotspot', src)
        self.assertIn('Ensure-SharingServicesLight', src)
        self.assertNotIn('Restart-NetworkSharingServicesSafe', src)
        self.assertNotIn('Restart-Service -Name $svc', src)

    def test_repair_reenables_mobile_hotspot(self) -> None:
        src = inspect.getsource(ics.repair_clumsy_network_sharing)
        self.assertIn('Ensure-MobileHotspotOn', src)
        self.assertIn('hotspotWasOn', src)
        self.assertIn('hotspotReenabled', src)

    def test_prepare_can_restart_tethering(self) -> None:
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        self.assertIn('Ensure-MobileHotspotOn', src)
        self.assertIn('Restart-SharedAccessSafe', src)

    def test_hotspot_helpers_use_winrt_await_not_2ghz_band(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Initialize-WinRtAwaitHelpers', helpers)
        self.assertIn('Wait-TetheringAsync', helpers)
        self.assertNotIn('Ensure-MobileHotspot2GhzBand', helpers)
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        self.assertNotIn('Ensure-MobileHotspot2GhzBand', src)

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
        self.assertNotIn('Restart-Service -Name $svc', src)
        self.assertIn('Ensure-WlanAutoConfigHealthy', src)
        self.assertIn('Ensure-SharingServicesLight', src)

    def test_prepare_pc_mobile_hotspot_automation(self) -> None:
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        self.assertIn('ZubCut-DHCP-In', src)
        self.assertIn('needs_manual_sharing', src)
        self.assertNotIn('Stop-Service icssvc', src.replace(' ', ''))

    def test_autodetect_prefers_hotspot_when_active(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Test-HotspotPathActive', helpers)
        detect_idx = helpers.index('function Detect-ClumsyConsolePath')
        hotspot_check = helpers.index('Test-HotspotPathActive', detect_idx)
        eth_idx = helpers.index('Find-EthernetConsoleAdapter', detect_idx)
        self.assertLess(hotspot_check, eth_idx)

    def test_ethernet_requires_connected_console_neighbor(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Test-ConsoleOnEthernetAdapter', helpers)
        self.assertNotIn('if ($ethUp.Count -eq 1)', helpers)

    def test_enable_failure_rolls_back_and_settings_stay_off(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn('repair_clumsy_network_sharing', src)
        settings = os.path.join(_ROOT, 'src', 'gui', 'settings.py')
        with open(settings, encoding='utf-8') as f:
            st = f.read()
        self.assertIn("self.chkClumsy.setChecked(False)", st)
        self.assertNotIn('Enable Clumsy mode anyway?', st)

    def test_hotspot_enable_internet_sharing_without_dhcp_only_exit(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn('Apply-InternetSharingForClumsy', src)
        self.assertIn('internet sharing enabled', src)
        self.assertNotIn("Write-ClumsyState $up $down $snapshot 'PC Mobile Hotspot ready (DHCP active).'", src)

    def test_prepare_enables_main_wifi_before_hotspot_toggle(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Apply-MainWifiSharingForHotspot', helpers)
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        self.assertIn('Apply-MainWifiSharingForHotspot', src)
        main_idx = src.index('Apply-MainWifiSharingForHotspot')
        auto_idx = src.index('Apply-HotspotIcsAutomated')
        self.assertLess(main_idx, auto_idx)

    def test_format_clumsy_ics_error_not_duplicated(self) -> None:
        raw = 'Turn ON Mobile Hotspot in Windows Settings first.'
        once = ics.format_clumsy_ics_error(raw, topology='hotspot')
        twice = ics.format_clumsy_ics_error(once, topology='hotspot')
        self.assertEqual(once, twice)
        self.assertEqual(once.count('For PS5 → PC Mobile Hotspot'), 1)
        self.assertEqual(once.count('Connect the PS5'), 1)

    def test_clumsy_ics_subnet_and_gateway(self) -> None:
        path = ics.clumsy_ics_state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        had = os.path.isfile(path)
        old = None
        try:
            if had:
                with open(path, encoding='utf-8') as f:
                    old = f.read()
            with open(path, 'w', encoding='utf-8') as f:
                f.write(
                    '{"downstream_prefix":"192.168.137.","downstream_ipv4":"192.168.137.1"}'
                )
            self.assertTrue(inline.victim_on_clumsy_ics_subnet('192.168.137.50'))
            self.assertFalse(inline.victim_on_clumsy_ics_subnet('192.168.1.50'))
            self.assertEqual(inline.clumsy_ics_downstream_prefix(), '192.168.137.')
        finally:
            if old is not None:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(old)
            elif not had and os.path.isfile(path):
                os.remove(path)

    def test_clumsy_ics_block_prefers_windivert_over_arp(self) -> None:
        self.assertIn('release_ics_victim_block', inline.__dict__)
        self.assertIn('IcsWinDivertLagGate', inspect.getsource(
            __import__('tools.ics_windivert_shaper', fromlist=['IcsWinDivertLagGate'])
        ))
        main_py = os.path.join(_SRC, 'gui', 'main.py')
        with open(main_py, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('def _apply_ics_client_block', src)
        self.assertIn('release_ics_victim_block', src)
        ics_block = src[src.index('def _apply_ics_client_block'):src.index('def _clear_ics_client_block')]
        self.assertIn('_ensure_ics_lag_gate', ics_block)
        self.assertIn('set_blocking(True)', ics_block)
        self.assertNotIn('apply_ics_victim_arp_block', ics_block)
        killer_py = os.path.join(_SRC, 'networking', 'killer.py')
        with open(killer_py, encoding='utf-8') as f:
            ksrc = f.read()
        self.assertIn('ics_mode=False', ksrc)
        self.assertIn('refresh_router=not ics_mode', ksrc)

    def test_ensure_network_skips_arp_flush_in_clumsy_mode(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('if not clumsy_mode_enabled():', src)
        self.assertIn('self.scanner.flush_arp()', src)
        self.assertIn('apply_clumsy_ics_router_context', src)

    def test_read_clumsy_topology_from_state_file(self) -> None:
        path = ics.clumsy_ics_state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        had = os.path.isfile(path)
        old = None
        try:
            if had:
                with open(path, encoding='utf-8') as f:
                    old = f.read()
            with open(path, 'w', encoding='utf-8') as f:
                f.write('{"topology":"ethernet"}')
            self.assertEqual(ics.read_clumsy_topology(), 'ethernet')
        finally:
            if old is not None:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(old)
            elif not had and os.path.isfile(path):
                os.remove(path)

    def test_startup_heals_wlan_autoconfig(self) -> None:
        zubcut = os.path.join(_SRC, 'zubcut.py')
        with open(zubcut, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('maybe_ensure_wlan_autoconfig_on_startup', src)
        self.assertIn('reset_clumsy_mode_on_startup', src)
        self.assertIn('ensure_wlan_autoconfig_healthy', inspect.getsource(ics))

    def test_reset_clumsy_mode_on_startup_clears_setting(self) -> None:
        from unittest.mock import patch

        def _get(key):
            return key == 'clumsy_mode'

        with patch('tools.utils_gui.get_settings', side_effect=_get), patch(
            'tools.utils_gui.set_settings'
        ) as ss:
            ics.reset_clumsy_mode_on_startup()
        ss.assert_called_once_with('clumsy_mode', False)

    def test_reset_clumsy_mode_skips_when_persist_flag_set(self) -> None:
        from unittest.mock import patch

        def _get(key):
            return key == 'clumsy_persist_across_restart'

        with patch('tools.utils_gui.get_settings', side_effect=_get), patch(
            'tools.utils_gui.set_settings'
        ) as ss:
            ics.reset_clumsy_mode_on_startup()
        ss.assert_called_once_with('clumsy_persist_across_restart', False)

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
