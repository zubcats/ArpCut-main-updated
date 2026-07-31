"""Windows IP forwarding must stay off while MITM victims are armed."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestIpForwardingMitm(unittest.TestCase):
    def test_stop_forwarder_does_not_enable_while_victims_armed(self) -> None:
        from networking.killer import Killer

        k = Killer.__new__(Killer)
        k.forwarders = {}
        k.killed = {'AA:BB:CC:DD:EE:FF': {'mac': 'AA:BB:CC:DD:EE:FF', 'ip': '192.168.1.165'}}
        with mock.patch('networking.killer.enable_ip_forwarding') as enable:
            k._stop_forwarder('AA:BB:CC:DD:EE:FF')
        enable.assert_not_called()

    def test_stop_forwarder_keeps_forwarding_off_when_idle(self) -> None:
        from networking.killer import Killer

        k = Killer.__new__(Killer)
        k.forwarders = {}
        k.killed = {}
        with (
            mock.patch('networking.killer.enable_ip_forwarding') as enable,
            mock.patch('networking.killer.disable_ip_forwarding') as disable,
        ):
            k._stop_forwarder('AA:BB:CC:DD:EE:FF')
        enable.assert_not_called()
        disable.assert_called_once()

    def test_kill_disables_forwarding_on_lan_path(self) -> None:
        from networking.killer import Killer

        k = Killer.__new__(Killer)
        k.iface = type('I', (), {'name': 'Wi-Fi', 'guid': '\\Device\\NPF_test', 'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.1.56'})()
        k.router = {'ip': '192.168.1.1', 'mac': '11:22:33:44:55:66'}
        k.killed = {}
        k.forwarders = {}
        k._op_seq = {}
        victim = {'mac': 'AA:BB:CC:DD:EE:FF', 'ip': '192.168.1.165'}
        with (
            mock.patch.object(Killer, '_sync_iface_for_victim'),
            mock.patch.object(Killer, '_refresh_victim_mac_from_cache'),
            mock.patch.object(Killer, '_next_op_seq', return_value=1),
            mock.patch.object(Killer, '_stop_forwarder'),
            mock.patch.object(Killer, '_poison_arp_now'),
            mock.patch.object(Killer, '_kill_arp_worker'),
            mock.patch.object(Killer, '_apply_traffic_cut_sync', return_value=False),
            mock.patch('networking.killer.disable_ip_forwarding') as disable,
        ):
            Killer.kill(k, victim, wait_after=0, traffic_cut=True, ics_mode=False)
        disable.assert_called_once()

    def test_set_windows_ip_forwarding_uses_per_iface_not_global_netsh(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('def _set_windows_ip_forwarding', src)
        self.assertIn('Set-NetIPInterface', src)
        self.assertIn('-Forwarding', src)
        # Old invalid global netsh command must not come back (silent no-op → leaky Kill).
        self.assertNotIn("'set', 'global', 'forwarding=", src)
        self.assertNotIn('["netsh", "interface", "ipv4", "set", "global"', src)

    def test_startup_does_not_reenable_forwarding_after_clean(self) -> None:
        path = os.path.join(_SRC, 'zubcut.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        # Startup cleans forwarding off; post-init must not turn it back on.
        self.assertIn('_ensure_clean_network_on_startup', src)
        block = src[src.index('GUI.scanner.init()') : src.index('reconcile_scanner_with_settings_iface')]
        self.assertNotIn('enable_ip_forwarding', block)

    def test_killer_init_does_not_enable_forwarding(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        init = src[src.index('def __init__(self, router=DUMMY_ROUTER)') : src.index('def _next_op_seq')]
        self.assertNotIn('enable_ip_forwarding()', init)
