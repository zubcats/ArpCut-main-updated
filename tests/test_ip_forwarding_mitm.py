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

    def test_stop_forwarder_enables_when_fully_idle(self) -> None:
        from networking.killer import Killer

        k = Killer.__new__(Killer)
        k.forwarders = {}
        k.killed = {}
        with mock.patch('networking.killer.enable_ip_forwarding') as enable:
            k._stop_forwarder('AA:BB:CC:DD:EE:FF')
        enable.assert_called_once()

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
