from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.killer import Killer


class MitmPrereqsTests(unittest.TestCase):
    def _killer(self) -> Killer:
        k = Killer.__new__(Killer)
        k.iface = MagicMock()
        k.iface.name = 'Ethernet'
        k.iface.guid = '{NPF_GUID}'
        k.iface.ip = '192.168.1.10'
        k.iface.mac = 'AA:BB:CC:DD:EE:FF'
        k.router = {
            'ip': '192.168.1.1',
            'mac': '11:22:33:44:55:66',
        }
        k._refresh_victim_mac_from_cache = MagicMock()
        return k

    def test_discovers_victim_mac_via_arp_before_failing(self) -> None:
        k = self._killer()
        victim = {'ip': '192.168.1.50', 'mac': ''}
        with patch(
            'networking.killer._lan_neighbor_mac_via_arp_probe',
            return_value='DE:AD:BE:EF:00:01',
        ), patch(
            'networking.killer.victim_endpoint_live_for_mitm',
            return_value=(True, ''),
        ):
            ok, reason = k.mitm_prereqs_ok(victim, ping_attempts=1)
        self.assertTrue(ok, reason)
        self.assertEqual(victim['mac'], 'DE:AD:BE:EF:00:01')

    def test_refreshes_router_mac_when_missing(self) -> None:
        k = self._killer()
        k.router['mac'] = ''
        victim = {'ip': '192.168.1.50', 'mac': 'DE:AD:BE:EF:00:01'}
        with patch.object(
            k, '_refresh_router_mac_for_mitm', side_effect=lambda: k.router.update(
                {'mac': '11:22:33:44:55:66'}
            )
        ), patch(
            'networking.killer._lan_neighbor_mac_via_arp_probe',
            return_value='DE:AD:BE:EF:00:01',
        ), patch(
            'networking.killer.victim_endpoint_live_for_mitm',
            return_value=(True, ''),
        ):
            ok, reason = k.mitm_prereqs_ok(victim, ping_attempts=1)
        self.assertTrue(ok, reason)


if __name__ == '__main__':
    unittest.main()
