"""MAC-centric device table (hotspot / Clumsy)."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking import device_table as dt


class _FakeScanner:
    router_ip = '192.168.1.1'
    my_ip = '192.168.137.1'
    devices = []


class TestDeviceTable(unittest.TestCase):
    def test_mac_centric_merges_lan_and_ics_hits(self) -> None:
        s = _FakeScanner()
        hits = [
            ('192.168.1.50', 'aa:bb:cc:dd:ee:ff'),
            ('192.168.137.42', 'aa:bb:cc:dd:ee:ff'),
        ]
        with (
            mock.patch.object(dt, 'clumsy_mac_centric_table', return_value=True),
            mock.patch.object(dt, '_ics_prefix', return_value='192.168.137.'),
            mock.patch('networking.device_table.Nicknames') as nick_cls,
        ):
            nick_cls.return_value.get_name.return_value = 'PS5'
            rows = dt.build_client_rows_from_scan(s, hits)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ip'], '192.168.137.42')
        self.assertEqual(rows[0]['mac'].lower(), 'aa:bb:cc:dd:ee:ff')
        self.assertEqual(rows[0].get('lan_ip'), '192.168.1.50')

    def test_refresh_upgrades_lan_row_to_ics_arp(self) -> None:
        s = _FakeScanner()
        s.devices = [
            {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.1.50', 'admin': False, 'name': '-'},
            {'mac': '00:11:22:33:44:55', 'ip': '10.0.0.1', 'admin': True, 'type': 'Me'},
        ]
        with (
            mock.patch.object(dt, 'clumsy_mac_centric_table', return_value=True),
            mock.patch.object(dt, '_ics_prefix', return_value='192.168.137.'),
            mock.patch('tools.clumsy_inline.clumsy_mode_enabled', return_value=True),
            mock.patch('tools.clumsy_inline.clumsy_runtime_ready', return_value=True),
            mock.patch('tools.clumsy_inline.clumsy_ics_arp_ip_for_mac', return_value='192.168.137.99'),
            mock.patch(
                'tools.clumsy_inline.clumsy_ics_resolve_victim_ip',
                return_value='192.168.137.99',
            ),
            mock.patch(
                'tools.clumsy_inline.victim_on_clumsy_ics_subnet',
                side_effect=lambda ip: str(ip).startswith('192.168.137.'),
            ),
            mock.patch('tools.clumsy_inline.detect_inline_ip', return_value=None),
            mock.patch('networking.device_table.Nicknames') as nick_cls,
        ):
            nick_cls.return_value.get_name.return_value = '-'
            dt.sync_device_table(s, allow_subnet_ping=False)
        clients = [d for d in s.devices if not d.get('admin')]
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]['ip'], '192.168.137.99')

    def test_revert_hides_hotspot_ip_when_clumsy_off(self) -> None:
        s = _FakeScanner()
        s.devices = [
            {
                'mac': 'dc:e9:94:ab:e6:c4',
                'ip': '192.168.137.194',
                'lan_ip': '192.168.1.165',
                'ics_ip': '192.168.137.194',
                'admin': False,
                'name': 'PS5',
            },
            {'mac': '00:11:22:33:44:55', 'ip': '10.0.0.1', 'admin': True, 'type': 'Me'},
        ]
        with (
            mock.patch('tools.clumsy_inline.clumsy_mode_enabled', return_value=False),
            mock.patch.object(dt, '_ics_prefix', return_value='192.168.137.'),
        ):
            dt.revert_clients_to_home_lan_display(s)
        clients = [d for d in s.devices if not d.get('admin')]
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]['ip'], '192.168.1.165')
        self.assertNotIn('ics_ip', clients[0])

    def test_phantom_favorite_skips_stale_lan_when_mac_present(self) -> None:
        s = _FakeScanner()
        s.devices = [
            {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.137.42', 'admin': False},
        ]
        with (
            mock.patch.object(dt, 'clumsy_mac_centric_table', return_value=True),
            mock.patch.object(dt, '_ics_prefix', return_value='192.168.137.'),
        ):
            skip = dt.phantom_favorite_should_skip(
                s, 'aa:bb:cc:dd:ee:ff', '192.168.1.50', set()
            )
        self.assertTrue(skip)


if __name__ == '__main__':
    unittest.main()
