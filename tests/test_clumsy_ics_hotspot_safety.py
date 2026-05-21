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
    def test_purge_stale_attack_blocks_does_not_raise(self) -> None:
        # Regression ZC-KPU5PP: purge used sys without importing it.
        result = ics.purge_clumsy_stale_attack_blocks()
        self.assertIsInstance(result, dict)
        self.assertIn('firewall_rules_removed', result)

    def test_enable_script_autodetects_console_path(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Detect-ClumsyConsolePath', helpers)
        self.assertIn('Find-EthernetConsoleAdapter', helpers)
        self.assertIn('Get-InternetUplinkAdapter', helpers)
        self.assertIn('Detect-ClumsyConsolePath', src)
        self.assertIn('Enable-MobileHotspotNatPath', src)
        self.assertNotIn('Prepare-ClumsyHotspotConsole', src)
        self.assertIn('purge_clumsy_stale_attack_blocks', inspect.getsource(ics.ensure_clumsy_ics_enabled))
        self.assertIn('netsh wlan stop hostednetwork', src)

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
        self.assertIn('Test-HotspotConsoleReady', src)
        self.assertIn('Apply-HotspotIcsCore', src)
        self.assertIn('Ensure-SharingServicesLight', src)
        self.assertNotIn('Restart-NetworkSharingServicesSafe', src)
        self.assertNotIn('Restart-Service -Name $svc', src)
        repair_hotspot_block = src.split('if ($hotspotWasOn) {', 1)[1].split('} else {', 1)[0]
        self.assertNotIn('Apply-HotspotIcsAutomated', repair_hotspot_block)
        self.assertNotIn('Repair-HotspotAdapterForConsole', src)

    def test_startup_does_not_reprep_hotspot_when_clumsy_on(self) -> None:
        src = inspect.getsource(ics.maybe_repair_stale_clumsy_ics_on_startup)
        self.assertIn('clumsy_mode_enabled', src)
        self.assertNotIn('prepare_pc_mobile_hotspot', src)
        self.assertIn('Do not re-run hotspot prep', src)

    def test_prepare_skips_when_hotspot_already_ready(self) -> None:
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Test-HotspotConsoleReady', helpers)
        self.assertIn('Test-HotspotConsoleReady', src)
        self.assertIn('Prepare-ClumsyHotspotConsole', helpers)
        self.assertIn('unchanged', helpers)

    def test_prepare_does_not_start_hotspot(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        prep_idx = helpers.index('function Prepare-ClumsyHotspotConsole')
        next_fn = helpers.index('function Detect-ClumsyConsolePath', prep_idx + 1)
        prep = helpers[prep_idx:next_fn]
        self.assertNotIn('Ensure-MobileHotspotOn', prep)

    def test_hotspot_helpers_use_winrt_await_not_2ghz_band(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Initialize-WinRtAwaitHelpers', helpers)
        self.assertIn('Wait-TetheringAsync', helpers)
        self.assertNotIn('Ensure-MobileHotspot2GhzBand', helpers)
        src = inspect.getsource(ics.prepare_pc_mobile_hotspot)
        self.assertNotIn('Ensure-MobileHotspot2GhzBand', src)

    def test_apply_hotspot_ics_core_only_touches_pair(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        core_idx = helpers.index('function Apply-HotspotIcsCore')
        next_fn = helpers.index('function Apply-HotspotIcs', core_idx + 1)
        core = helpers[core_idx:next_fn]
        self.assertIn('DisableSharingOnGuid', core)
        self.assertIn('never wipe ICS on other adapters', core)
        self.assertNotIn('foreach ($k in $connMap.Keys)', core)

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
        self.assertIn('needs_manual_sharing', src)
        self.assertNotIn('Stop-Service icssvc', src.replace(' ', ''))
        self.assertNotIn('Disable-NetAdapterBinding', src)

    def test_autodetect_prefers_hotspot_before_spare_ethernet(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Test-HotspotPathActive', helpers)
        detect_idx = helpers.index('function Detect-ClumsyConsolePath')
        eth_idx = helpers.index('Find-EthernetConsoleAdapter', detect_idx)
        hotspot_check = helpers.index('Test-HotspotPathActive', detect_idx)
        self.assertLess(hotspot_check, eth_idx)

    def test_autodetect_tracks_uplink_kind(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Get-UplinkKindLabel', helpers)
        self.assertIn('UplinkKind', helpers)
        self.assertIn('LikelyEthernetNic $_', helpers)
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn('uplink_kind', src)
        self.assertIn('Disconnect-WifiClientWhenEthernetUplink', helpers)
        self.assertNotIn('Prepare-ClumsyHotspotConsole', src)

    def test_enable_fails_fast_without_auto_hotspot_prep(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        detect_block = src.split('$detect = Detect-ClumsyConsolePath', 1)[1].split('$ZubcutTopology', 1)[0]
        self.assertNotIn('Prepare-ClumsyHotspotConsole', detect_block)
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('No valid console path detected', helpers)
        self.assertNotIn('will start Mobile Hotspot', helpers)

    def test_ethernet_requires_connected_console_neighbor(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Test-ConsoleOnEthernetAdapter', helpers)
        self.assertNotIn('if ($ethUp.Count -eq 1) { return $ethUp[0] }', helpers)

    def test_hotspot_operational_without_classic_ics(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('function Test-MobileHotspotOperational', helpers)
        self.assertIn('function Test-ClumsyHotspotPathReady', helpers)
        self.assertIn('function Enable-MobileHotspotNatPath', helpers)
        self.assertIn('function Set-HotspotDhcpRegistry', helpers)
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn('Enable-MobileHotspotNatPath', src)
        self.assertIn('$natAlready', src)
        self.assertIn('ZubCut enabled Mobile Hotspot NAT', src)
        self.assertIn('NAT already active', src)
        helpers_block = helpers[helpers.index('function Enable-MobileHotspotNatPath'):helpers.index('function Test-HotspotIcsActive')]
        self.assertIn('if (Test-MobileHotspotOperational)', helpers_block)
        self.assertIn('return $true', helpers_block)

    def test_hotspot_enable_skips_disrupt_when_already_ok(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        helpers = ics._PS_HOTSPOT_HELPERS
        self.assertIn('Test-HotspotConsoleReady', helpers)
        hotspot_idx = src.index("if ($ZubcutTopology -eq 'hotspot')")
        eth_idx = src.index('} else {', hotspot_idx)
        hotspot_block = src[hotspot_idx:eth_idx]
        self.assertIn('$alreadyOk', hotspot_block)
        self.assertIn('Test-ClumsyHotspotPathReady', hotspot_block)
        self.assertIn('sharing already active', hotspot_block)
        self.assertIn('Apply-HotspotIcsCore', src)
        self.assertNotIn('Prepare-ClumsyHotspotConsole', hotspot_block)
        self.assertNotIn('Apply-HotspotIcsWithTetheringToggle', hotspot_block)
        self.assertNotIn('Ensure-MainWifiSharingForClumsy', hotspot_block)

    def test_ethernet_enable_skips_ics_when_already_active(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        eth_idx = src.index("} else {", src.index("if ($ZubcutTopology -eq 'hotspot')"))
        eth_block = src[eth_idx:]
        self.assertIn('ICS already active', eth_block)
        self.assertIn('Apply-HotspotIcsCore $ethPair', eth_block)
        self.assertNotIn('Apply-ICS $privFirst', eth_block)

    def test_apply_hotspot_ics_core_skips_when_already_active(self) -> None:
        helpers = ics._PS_HOTSPOT_HELPERS
        core_idx = helpers.index('function Apply-HotspotIcsCore')
        next_fn = helpers.index('function Apply-HotspotIcs', core_idx + 1)
        core = helpers[core_idx:next_fn]
        self.assertIn('Test-IcsActiveForPair', core)

    def test_enable_failure_rolls_back_and_settings_stay_off(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn('_retry_main_wifi_sharing_for_hotspot', src)
        settings = os.path.join(_ROOT, 'src', 'gui', 'settings.py')
        with open(settings, encoding='utf-8') as f:
            st = f.read()
        self.assertIn("self.chkClumsy.setChecked(False)", st)
        self.assertNotIn('Enable Clumsy mode anyway?', st)

    def test_hotspot_enable_internet_sharing_without_dhcp_only_exit(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn('Apply-HotspotIcsCore', src)
        self.assertIn('Clumsy mode ready', src)
        self.assertNotIn("Write-ClumsyState $up $down $snapshot 'PC Mobile Hotspot ready (DHCP active).'", src)

    def test_format_clumsy_ics_error_not_duplicated(self) -> None:
        raw = 'Turn ON Mobile Hotspot in Windows Settings first.'
        once = ics.format_clumsy_ics_error(raw, topology='hotspot')
        twice = ics.format_clumsy_ics_error(once, topology='hotspot')
        self.assertEqual(once, twice)
        self.assertEqual(once.count('Valid hotspot path for Clumsy mode'), 1)
        self.assertIn('console on PC hotspot', once)

    def test_clumsy_hotspot_session_active_resolves_topology(self) -> None:
        """Regression ZC-4VZ0ZQ: read_clumsy_topology must be imported in clumsy_inline."""
        from unittest.mock import patch

        with patch.object(inline, 'clumsy_mode_enabled', return_value=False):
            self.assertFalse(inline.clumsy_hotspot_session_active())
        with patch.object(inline, 'clumsy_mode_enabled', return_value=True), patch(
            'tools.clumsy_ics.read_clumsy_topology', return_value='hotspot'
        ):
            self.assertTrue(inline.clumsy_hotspot_session_active())

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

    def test_windivert_gate_keeps_recv_loop_on_idle(self) -> None:
        from tools import ics_windivert_shaper as wd

        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        self.assertIn('ERROR_NO_DATA', src)
        self.assertIn('continue', src)
        self.assertNotRegex(
            src,
            r'if err == ERROR_NO_DATA:\s*\n\s*break',
        )

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
        self.assertTrue(
            'pause_connection' in ics_block or 'set_blocking(' in ics_block,
            'ICS block must use WinDivert pause, not ARP MITM',
        )
        wd_mod = __import__('tools.ics_windivert_shaper', fromlist=['IcsWinDivertLagGate'])
        gate_src = inspect.getsource(wd_mod.IcsWinDivertLagGate)
        wd_src = inspect.getsource(wd_mod)
        self.assertIn('prepare_stop', gate_src)
        self.assertIn('_discard_heap', gate_src)
        self.assertIn('_hold_pause', gate_src)
        self.assertIn('_PAUSE_HOLD_DUE', gate_src)
        self.assertIn('WINDIVERT_LAYER_NETWORK_FORWARD', wd_src)
        self.assertIn('192.168.137.', wd_src)
        self.assertIn('WINDIVERT_LAYER_NETWORK', wd_src)
        self.assertNotIn('apply_ics_victim_arp_block', ics_block)
        layers_src = inspect.getsource(wd_mod._layers_for_capture_desc)
        self.assertIn(
            '(WINDIVERT_LAYER_NETWORK_FORWARD, WINDIVERT_LAYER_NETWORK)',
            layers_src.replace('\n', ' '),
        )
        self.assertIn('_ics_windivert_filter', wd_src)
        start_src = gate_src[gate_src.index('def start'): gate_src.index('def set_blocking')]
        self.assertIn('_open_windivert_handles', start_src)
        self.assertIn('self._handles = [h for h', start_src)
        self.assertIn('_ics_windivert_filter', wd_src)
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

        with patch(
            'tools.clumsy_ics.consume_clumsy_settings_restart_pending',
            return_value=False,
        ), patch(
            'tools.utils_gui.import_settings_as_dict',
            return_value={'clumsy_mode': True, 'clumsy_persist_across_restart': False},
        ), patch('tools.utils_gui.set_settings_many') as sm:
            ics.reset_clumsy_mode_on_startup()
        sm.assert_called_once_with({'clumsy_mode': False})

    def test_reset_clumsy_mode_skips_when_restart_marker_present(self) -> None:
        from unittest.mock import patch

        with patch(
            'tools.clumsy_ics.consume_clumsy_settings_restart_pending',
            return_value=True,
        ), patch('tools.utils_gui.set_settings_many') as sm:
            ics.reset_clumsy_mode_on_startup()
        sm.assert_not_called()

    def test_reset_clumsy_mode_skips_when_persist_flag_set(self) -> None:
        from unittest.mock import patch

        with patch(
            'tools.clumsy_ics.consume_clumsy_settings_restart_pending',
            return_value=False,
        ), patch(
            'tools.utils_gui.import_settings_as_dict',
            return_value={'clumsy_mode': True, 'clumsy_persist_across_restart': True},
        ), patch('tools.utils_gui.set_settings_many') as sm:
            ics.reset_clumsy_mode_on_startup()
        sm.assert_called_once_with({'clumsy_persist_across_restart': False})

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

    def test_flush_arp_skips_on_hotspot_subnet(self) -> None:
        from unittest.mock import MagicMock, patch

        from networking.scanner import Scanner

        sc = Scanner()
        sc.my_ip = '192.168.137.1'
        with patch('tools.clumsy_inline.hotspot_arp_cache_sensitive', return_value=True):
            with patch('networking.scanner.terminal') as term:
                sc.flush_arp()
        term.assert_not_called()

    def test_startup_teardown_does_not_clear_killed_before_unkill(self) -> None:
        main_py = os.path.join(_SRC, 'gui', 'main.py')
        with open(main_py, encoding='utf-8') as fh:
            src = fh.read()
        block = src.split('def _ensure_clean_network_on_startup', 1)[1].split('\n    def ', 1)[0]
        self.assertNotIn('self.killer.killed.clear()', block)
        self.assertIn('heal_all_hotspot_arp_clients', block)

    def test_unkill_all_uses_ics_router_context(self) -> None:
        from networking.killer import Killer

        src = inspect.getsource(Killer.unkill_all)
        self.assertIn('apply_clumsy_ics_router_context', src)
        self.assertIn('ics_mode=True', src)
        self.assertIn('heal_ics_client_after_mitm', src)

    def test_parse_ics_arp_entries(self) -> None:
        text = (
            'Interface: 192.168.137.1 --- 0x15\n'
            '  192.168.137.2          ab-cd-ef-12-34-56     dynamic\n'
            '  192.168.1.50           11-22-33-44-55-66     dynamic\n'
        )
        rows = inline._parse_ics_arp_entries(
            text,
            '192.168.137.1',
            '192.168.137.1',
            '192.168.137.',
            '192.168.137.1',
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ip'], '192.168.137.2')
        self.assertEqual(rows[0]['mac'], 'AB:CD:EF:12:34:56')


if __name__ == '__main__':
    unittest.main()
