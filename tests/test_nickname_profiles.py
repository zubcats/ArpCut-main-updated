"""Per-subnet nickname profiles (MAC|subnet keys)."""
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
    Nicknames,
    ipv4_subnet_prefix,
    nickname_profile_key,
    parse_nickname_profile_key,
)


class TestNicknameProfiles(unittest.TestCase):
    def test_profile_key_includes_subnet(self) -> None:
        pk = nickname_profile_key('aa:bb:cc:dd:ee:ff', '192.168.137.50')
        self.assertEqual(pk, 'AA:BB:CC:DD:EE:FF|192.168.137')
        self.assertEqual(ipv4_subnet_prefix('10.0.0.8'), '10.0.0')

    def test_separate_names_per_subnet(self) -> None:
        mac = 'aa:bb:cc:dd:ee:ff'
        db = {}
        last = {}

        def fake_get(key):
            if key == 'nicknames':
                return db
            if key == 'nickname_last_ip':
                return last
            return None

        def fake_set(key, val):
            if key == 'nicknames':
                db.clear()
                db.update(val)
            elif key == 'nickname_last_ip':
                last.clear()
                last.update(val)

        with mock.patch('networking.nicknames.get_settings', side_effect=fake_get):
            with mock.patch('networking.nicknames.set_settings', side_effect=fake_set):
                with mock.patch('networking.nicknames.migrate_nickname_storage'):
                    n = Nicknames()
                    n.set_name(mac, 'PS5 Hotspot', '192.168.137.50')
                    n.set_name(mac, 'PS5 Home', '192.168.1.165')
        self.assertEqual(n.get_name(mac, '192.168.137.50'), 'PS5 Hotspot')
        self.assertEqual(n.get_name(mac, '192.168.1.165'), 'PS5 Home')

    def test_parse_profile_key(self) -> None:
        mac, prefix = parse_nickname_profile_key('aa:bb:cc:dd:ee:ff|192.168.1')
        self.assertEqual(prefix, '192.168.1')

    def test_kill_profile_keys_differ_by_subnet(self) -> None:
        mac = 'aa:bb:cc:dd:ee:ff'
        home = nickname_profile_key(mac, '192.168.1.165')
        hotspot = nickname_profile_key(mac, '192.168.137.50')
        self.assertNotEqual(home, hotspot)
        self.assertEqual(home, 'AA:BB:CC:DD:EE:FF|192.168.1')
        self.assertEqual(hotspot, 'AA:BB:CC:DD:EE:FF|192.168.137')


if __name__ == '__main__':
    unittest.main()
