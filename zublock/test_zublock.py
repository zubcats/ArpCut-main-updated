"""ZubLock unit tests (no WinDivert, no window)."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

import zublock_engine
import zublock_gui
import zublock_rules

ROOT = Path(__file__).resolve().parent


def _ipv4_tcp(src: str, dst: str, sport: int, dport: int, flags: int = 0x18) -> bytes:
    src_b = bytes(int(x) for x in src.split('.'))
    dst_b = bytes(int(x) for x in dst.split('.'))
    ip = struct.pack('!BBHHHBBH', 0x45, 0, 40, 0, 0, 64, 6, 0) + src_b + dst_b
    tcp = struct.pack('!HHIIBBHHH', sport, dport, 0, 0, 5 << 4, flags, 8192, 0, 0)
    return ip + tcp


def _ipv4_udp(src: str, dst: str, sport: int, dport: int) -> bytes:
    src_b = bytes(int(x) for x in src.split('.'))
    dst_b = bytes(int(x) for x in dst.split('.'))
    ip = struct.pack('!BBHHHBBH', 0x45, 0, 28, 0, 0, 64, 17, 0) + src_b + dst_b
    udp = struct.pack('!HHHH', sport, dport, 8, 0)
    return ip + udp


class TestRules(unittest.TestCase):
    def test_default_ranges_drop_psn_aws_https_only(self) -> None:
        rules = zublock_rules.load_ranges(ROOT / 'lock_ranges.txt')
        self.assertEqual(
            rules,
            {
                ('TCP', '44.234.0.0/16', 443),
                ('TCP', '35.164.0.0/15', 443),
                ('TCP', '35.155.0.0/16', 443),
            },
        )
        self.assertTrue(
            zublock_rules.should_drop(
                '192.168.137.64', '44.234.12.9', 'TCP', 12345, 443, rules
            )
        )
        self.assertTrue(
            zublock_rules.should_drop(
                '35.155.1.2', '192.168.137.64', 'TCP', 443, 12345, rules
            )
        )
        self.assertTrue(
            zublock_rules.should_drop(
                '192.168.137.64', '35.165.189.106', 'TCP', 9, 443, rules
            )
        )
        self.assertFalse(
            zublock_rules.should_drop(
                '192.168.137.64', '85.190.158.101', 'UDP', 10200, 10200, rules
            )
        )
        self.assertFalse(
            zublock_rules.should_drop(
                '192.168.137.64', '23.222.17.202', 'TCP', 12345, 443, rules
            )
        )

    def test_comments_and_newsyn(self) -> None:
        rules = zublock_rules.parse_drop_keys('# x\nNEWSYN\n')
        self.assertEqual(rules, {('NEWSYN', '', 0)})
        self.assertTrue(
            zublock_rules.should_drop(
                '192.168.137.64', '1.2.3.4', 'TCP', 1, 443, rules, flags='S'
            )
        )
        self.assertFalse(
            zublock_rules.should_drop(
                '192.168.137.64', '1.2.3.4', 'TCP', 1, 443, rules, flags='PA'
            )
        )


class TestEngineParse(unittest.TestCase):
    def test_parse_ipv4_tcp_syn(self) -> None:
        raw = _ipv4_tcp('192.168.137.64', '44.234.1.1', 50000, 443, flags=0x02)
        got = zublock_engine.parse_ipv4(raw)
        self.assertEqual(got, ('192.168.137.64', '44.234.1.1', 'TCP', 50000, 443, 'S'))

    def test_parse_ipv4_udp_game(self) -> None:
        raw = _ipv4_udp('192.168.137.64', '85.190.158.101', 10200, 10200)
        got = zublock_engine.parse_ipv4(raw)
        self.assertEqual(got, ('192.168.137.64', '85.190.158.101', 'UDP', 10200, 10200, ''))

    def test_invalid_handle(self) -> None:
        self.assertFalse(zublock_engine._handle_ok(None))
        self.assertFalse(zublock_engine._handle_ok(0))
        self.assertFalse(zublock_engine._handle_ok(zublock_engine.INVALID_HANDLE))
        self.assertTrue(zublock_engine._handle_ok(1234))

    def test_hotspot_prefers_sony_mac(self) -> None:
        arp = (
            'Interface: 192.168.137.1 --- 0x12\n'
            '  192.168.137.20           11-22-33-44-55-66     dynamic\n'
            '  192.168.137.64           f8-da-0c-db-e3-b5     dynamic\n'
        )
        self.assertEqual(zublock_engine.discover_hotspot_console(arp), '192.168.137.64')

    def test_hotspot_ignores_extra_arp_row_same_mac(self) -> None:
        arp = (
            'Interface: 192.168.137.1 --- 0xd\n'
            '  192.168.137.64           f8-da-0c-db-e3-b5     static\n'
            '  192.168.137.248          f8-da-0c-db-e3-b5     static\n'
        )
        self.assertEqual(zublock_engine.discover_hotspot_clients(arp), ['192.168.137.64'])

    def test_capture_filter_is_whole_hotspot_not_one_ip(self) -> None:
        filt = zublock_engine.capture_filters('192.168.137.64')
        self.assertTrue(filt[0].startswith('('))
        self.assertIn('192.168.137.0/24', filt[0])
        self.assertNotIn('192.168.137.64', filt[0])
        self.assertIn('!impostor', filt[0])
        self.assertGreater(zublock_engine.WINDIVERT_PRIORITY, 0)


class TestInstaller(unittest.TestCase):
    def test_setup_script_and_inno_are_named_zublock(self) -> None:
        self.assertTrue((ROOT / 'ZubLock-Setup.cmd').is_file())
        iss = ROOT.parent / 'installer' / 'ZubLock.iss'
        text = iss.read_text(encoding='utf-8')
        self.assertIn('#define MyAppName "ZubLock"', text)
        self.assertIn(r'{autodesktop}\{#MyAppName}', text)
        self.assertIn('zublock.ico', text)
        self.assertIn('OutputBaseFilename=ZubLock-Setup', text)
        self.assertNotIn('#19232D', text)


class TestGuiTheme(unittest.TestCase):
    def test_charcoal_tokens_and_title(self) -> None:
        self.assertEqual(zublock_gui.BG, '#141414')
        self.assertEqual(zublock_gui.BTN, '#2b2b2b')
        self.assertEqual(zublock_gui.BORDER, '#3d3d3d')
        self.assertEqual(zublock_gui.ACCENT, '#316E69')
        self.assertNotIn('#19232D', Path(zublock_gui.__file__).read_text(encoding='utf-8'))
        self.assertTrue((ROOT / 'zublock.ico').is_file())


if __name__ == '__main__':
    unittest.main()
