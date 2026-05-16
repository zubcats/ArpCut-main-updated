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

    def test_startup_heals_wlan_autoconfig(self) -> None:
        zubcut = os.path.join(_SRC, 'zubcut.py')
        with open(zubcut, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('maybe_ensure_wlan_autoconfig_on_startup', src)
        self.assertIn('ensure_wlan_autoconfig_healthy', inspect.getsource(ics))

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
