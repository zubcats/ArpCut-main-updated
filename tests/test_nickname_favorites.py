"""Startup favorite rows: legacy keys, ARP refresh, stale ghost suppression."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.nicknames import (
    _last_ip_for_mac,
    migrate_nickname_storage,
    resolve_favorite_ip,
    stale_nickname_favorite_should_skip,
)
from tools.utils import repair_nickname_last_ips_from_arp


class TestNicknameFavorites(unittest.TestCase):
    def test_last_ip_for_mac_finds_profile_key(self) -> None:
        mac = '00:E4:21:44:ED:0C'
        last = {'00:E4:21:44:ED:0C|192.168.1': '192.168.1.248'}
        self.assertEqual(_last_ip_for_mac(mac, last), '192.168.1.248')

    def test_resolve_favorite_ip_prefers_arp(self) -> None:
        mac = '00:E4:21:44:ED:0C'
        last = {'00:E4:21:44:ED:0C|192.168.1': '192.168.1.165'}
        with mock.patch(
            'tools.utils.lookup_ip_from_arp_table', return_value='192.168.1.248'
        ):
            ip = resolve_favorite_ip(mac, mac, last, '192.168.1.56')
        self.assertEqual(ip, '192.168.1.248')

    def test_stale_dupe_skipped_when_ip_owned_by_other_mac(self) -> None:
        dupe_mac = 'DC:E9:94:AB:E6:C4'
        ps5_mac = '00:E4:21:44:ED:0C'
        with (
            mock.patch('tools.utils.lookup_ip_from_arp_table', return_value=''),
            mock.patch('tools.utils.lookup_mac_from_arp_table', return_value=ps5_mac),
        ):
            skip = stale_nickname_favorite_should_skip(
                dupe_mac, '192.168.1.165', '192.168.1.56'
            )
        self.assertTrue(skip)

    def test_repair_drops_stale_last_ip_when_mac_not_in_arp(self) -> None:
        ps5 = '00:E4:21:44:ED:0C'
        dupe = 'DC:E9:94:AB:E6:C4'
        nicknames = {
            f'{ps5}|192.168.1': 'PS5',
            f'{dupe}|192.168.1': 'PS5 DUPE',
        }
        last = {
            f'{ps5}|192.168.1': '192.168.1.248',
            f'{dupe}|192.168.1': '192.168.1.165',
        }

        def fake_lookup_ip(mac: str, _iface: str) -> str:
            if mac == ps5:
                return '192.168.1.248'
            return ''

        def fake_lookup_mac(ip: str, _iface: str) -> str:
            if ip == '192.168.1.165':
                return ps5
            if ip == '192.168.1.248':
                return ps5
            return ''

        with (
            mock.patch('tools.utils.pick_best_live_iface', return_value=mock.Mock(ip='192.168.1.56')),
            mock.patch('tools.utils._iface_live_ipv4', return_value='192.168.1.56'),
            mock.patch('tools.utils.lookup_ip_from_arp_table', side_effect=fake_lookup_ip),
            mock.patch('tools.utils.lookup_mac_from_arp_table', side_effect=fake_lookup_mac),
        ):
            repaired = repair_nickname_last_ips_from_arp(last, nicknames)
        self.assertEqual(repaired.get(f'{ps5}|192.168.1'), '192.168.1.248')
        self.assertNotIn(f'{dupe}|192.168.1', repaired)

    def test_migrate_legacy_nickname_uses_profile_last_ip(self) -> None:
        mac = '00:E4:21:44:ED:0C'
        db = {mac: 'PS5'}
        last = {f'{mac}|192.168.1': '192.168.1.248'}

        def fake_get(key):
            if key == 'nicknames':
                return dict(db)
            if key == 'nickname_last_ip':
                return dict(last)
            return None

        saved = {}

        def fake_set(key, val):
            saved[key] = val

        with (
            mock.patch('networking.nicknames.get_settings', side_effect=fake_get),
            mock.patch('networking.nicknames.set_settings', side_effect=fake_set),
            mock.patch('tools.utils.repair_nickname_last_ips_from_arp', side_effect=lambda l, n: l),
        ):
            migrate_nickname_storage()
        self.assertIn(f'{mac}|192.168.1', saved.get('nicknames', {}))
        self.assertNotIn(mac, saved.get('nicknames', {}))


if __name__ == '__main__':
    unittest.main()
