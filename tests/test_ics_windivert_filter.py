"""ICS WinDivert filter and victim IP resolution."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import ics_windivert_shaper as wd
from tools import clumsy_inline as inline


class TestIcsWinDivertFilter(unittest.TestCase):
    def test_hotspot_uses_subnet_filter(self) -> None:
        filt = wd._ics_windivert_filter('192.168.137.50', '192.168.137.')
        self.assertIn('192.168.137.2', filt)
        self.assertIn('192.168.137.254', filt)
        self.assertNotIn('192.168.137.50', filt)

    def test_other_subnet_uses_victim_quad(self) -> None:
        filt = wd._ics_windivert_filter('10.0.0.8', '192.168.137.')
        self.assertIn('10.0.0.8', filt)

    def test_hotspot_client_packet_match_subnet(self) -> None:
        self.assertTrue(
            wd._packet_matches_hotspot_client(
                '192.168.137.194', '8.8.8.8', '192.168.137.194', '192.168.137.'
            )
        )
        self.assertFalse(
            wd._packet_matches_hotspot_client(
                '192.168.1.165', '8.8.8.8', '192.168.137.194', '192.168.137.'
            )
        )

    def test_resolve_victim_ip_from_arp_table(self) -> None:
        device = {'ip': '', 'mac': 'aa:bb:cc:dd:ee:ff'}
        cache = (
            'Interface: 192.168.137.1 --- 0x42\n'
            '  192.168.137.50        aa-bb-cc-dd-ee-ff     dynamic\n'
        )

        with mock.patch('tools.utils.terminal', side_effect=lambda c: cache if 'arp' in c else ''):
            with unittest.mock.patch.object(inline, 'clumsy_mode_enabled', return_value=True):
                with unittest.mock.patch.object(inline, 'victim_on_clumsy_ics_subnet', side_effect=lambda ip: str(ip).startswith('192.168.137.')):
                    with unittest.mock.patch.object(inline, 'clumsy_ics_downstream_prefix', return_value='192.168.137.'):
                        with unittest.mock.patch.object(inline, 'read_clumsy_ics_state', return_value={'downstream_ipv4': '192.168.137.1'}):
                            ip = inline.clumsy_ics_resolve_victim_ip(device)
        self.assertEqual(ip, '192.168.137.50')

    def test_resolve_keeps_home_lan_table_ip(self) -> None:
        device = {'ip': '192.168.1.248', 'mac': 'aa:bb:cc:dd:ee:ff'}
        with unittest.mock.patch.object(inline, 'clumsy_mode_enabled', return_value=True):
            with unittest.mock.patch.object(
                inline,
                'victim_on_clumsy_ics_subnet',
                side_effect=lambda ip: str(ip).startswith('192.168.137.'),
            ):
                with unittest.mock.patch.object(
                    inline, 'clumsy_ics_arp_ip_for_mac', return_value='192.168.137.50'
                ):
                    ip = inline.clumsy_ics_resolve_victim_ip(device)
        self.assertEqual(ip, '192.168.1.248')


if __name__ == '__main__':
    unittest.main()
