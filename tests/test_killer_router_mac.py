"""Keep a known gateway MAC when iface sync's ARP lookup is empty."""
from __future__ import annotations

import os
import sys
import threading
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from constants import GLOBAL_MAC
from networking.ifaces import NetFace
from networking.killer import Killer
from tools.utils import mac_address_is_usable


def _face(name: str, guid: str, ip: str) -> NetFace:
    return NetFace(
        {
            'name': name,
            'guid': guid,
            'mac': 'aa:aa:aa:aa:aa:aa',
            'ips': [ip],
        }
    )


class TestSyncIfaceKeepsRouterMac(unittest.TestCase):
    def _killer(self, iface: NetFace) -> Killer:
        k = Killer.__new__(Killer)
        k.iface = iface
        k.router = {'ip': '192.168.1.1', 'mac': '74:24:9f:37:1e:ec'}
        k._socket = object()
        k._socket_token = 'x'
        k._socket_lock = threading.RLock()
        return k

    def test_keeps_usable_router_mac_when_lookup_empty(self) -> None:
        wifi = _face('Wi-Fi', r'\Device\NPF_{5B106E08-1111-1111-1111-111111111111}', '192.168.1.56')
        eth = _face('Ethernet', r'\Device\NPF_{AAAAAAAA-1111-1111-1111-111111111111}', '192.168.1.110')
        k = self._killer(wifi)
        with (
            mock.patch('networking.killer.get_iface_for_victim_ip', return_value=eth),
            mock.patch('networking.killer.bind_scapy_conf_iface'),
            mock.patch('networking.killer.get_my_ip', return_value='192.168.1.110'),
            mock.patch('networking.killer.get_gateway_ip', return_value='192.168.1.1'),
            mock.patch('networking.killer.get_gateway_mac', return_value=GLOBAL_MAC),
            mock.patch.object(k, '_close_socket'),
        ):
            k._sync_iface_for_victim(
                {'ip': '192.168.1.165', 'mac': 'dc:e9:94:ab:e6:c4'}
            )
        self.assertEqual(str(k.router['mac']).lower(), '74:24:9f:37:1e:ec')
        self.assertEqual(k.router['ip'], '192.168.1.1')

    def test_does_not_keep_mac_when_gateway_ip_changes(self) -> None:
        wifi = _face('Wi-Fi', r'\Device\NPF_{5B106E08-1111-1111-1111-111111111111}', '192.168.1.56')
        ics = _face(
            'Local Area Connection* 10',
            r'\Device\NPF_{BBBBBBBB-1111-1111-1111-111111111111}',
            '192.168.137.1',
        )
        k = self._killer(wifi)
        with (
            mock.patch('networking.killer.get_iface_for_victim_ip', return_value=ics),
            mock.patch('networking.killer.bind_scapy_conf_iface'),
            mock.patch('networking.killer.get_my_ip', return_value='192.168.137.1'),
            mock.patch('networking.killer.get_gateway_ip', return_value='192.168.137.1'),
            mock.patch('networking.killer.get_gateway_mac', return_value=GLOBAL_MAC),
            mock.patch.object(k, '_close_socket'),
        ):
            k._sync_iface_for_victim(
                {'ip': '192.168.137.50', 'mac': 'dc:e9:94:ab:e6:c4'}
            )
        self.assertFalse(mac_address_is_usable(k.router.get('mac')))
        self.assertEqual(k.router['ip'], '192.168.137.1')


if __name__ == '__main__':
    unittest.main()
