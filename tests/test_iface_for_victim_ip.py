"""Iface pick when PC switches Ethernet ↔ Wi‑Fi on the same LAN."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.ifaces import NetFace
from tools.utils import get_iface_for_victim_ip


def _face(name: str, guid: str, ip: str) -> NetFace:
    return NetFace({'name': name, 'guid': guid, 'mac': '00:11:22:33:44:55', 'ips': [ip]})


class TestIfaceForVictimIp(unittest.TestCase):
    @patch('tools.utils.get_ifaces_cached')
    @patch('tools.utils.get_my_ip')
    @patch('tools.utils.conf')
    def test_route_picks_wifi_when_ethernet_unplugged(
        self, mock_conf, mock_my_ip, mock_cached
    ) -> None:
        eth = _face('Ethernet', r'\\Device\\NPF_{ETH}', '192.168.1.110')
        wifi = _face('Wi-Fi', r'\\Device\\NPF_{WIFI}', '192.168.1.56')
        mock_cached.return_value = [eth, wifi]

        def _my_ip(guid: str) -> str:
            if 'WIFI' in str(guid):
                return '192.168.1.56'
            return '0.0.0.0'

        mock_my_ip.side_effect = _my_ip
        mock_conf.route.route.return_value = (
            '0.0.0.0',
            '0.0.0.0',
            '0.0.0.0',
            wifi.guid,
            '192.168.1.56',
        )
        got = get_iface_for_victim_ip('192.168.1.248', fallback=eth)
        self.assertEqual(got.guid, wifi.guid)

    @patch('tools.utils.get_ifaces_cached')
    @patch('tools.utils.get_my_ip')
    @patch('tools.utils.conf')
    def test_stale_fallback_not_used_without_live_ip(
        self, mock_conf, mock_my_ip, mock_cached
    ) -> None:
        eth = _face('Ethernet', r'\\Device\\NPF_{ETH}', '192.168.1.110')
        wifi = _face('Wi-Fi', r'\\Device\\NPF_{WIFI}', '192.168.1.56')
        mock_cached.return_value = [eth, wifi]
        mock_my_ip.side_effect = lambda guid: (
            '192.168.1.56' if 'WIFI' in str(guid) else '0.0.0.0'
        )
        mock_conf.route.route.return_value = None
        mock_conf.route.routes = []
        got = get_iface_for_victim_ip('192.168.1.248', fallback=eth)
        self.assertEqual(got.guid, wifi.guid)
