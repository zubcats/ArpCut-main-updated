"""Prefer DHCP LAN IPv4 over APIPA (169.254.x.x) for Me row and iface pick."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.utils import (
    NetFace,
    _ipconfig_adapter_name_from_header,
    _ipconfig_line_is_adapter_header,
    _ipconfig_line_is_host_ipv4,
    _prefer_ipv4,
    get_my_ip,
    resolve_iface_my_ip,
)


class TestApipaIp(unittest.TestCase):
    def test_prefer_ipv4_keeps_first_usable_host(self) -> None:
        self.assertEqual(_prefer_ipv4('192.168.1.56', '192.168.1.1'), '192.168.1.56')
        self.assertEqual(_prefer_ipv4('192.168.1.56', '169.254.1.1'), '192.168.1.56')

    def test_ipconfig_skips_gateway_line(self) -> None:
        self.assertTrue(_ipconfig_line_is_host_ipv4('IPv4 Address. . . . . . : 192.168.1.56'))
        self.assertFalse(_ipconfig_line_is_host_ipv4('Default Gateway . . . . : 192.168.1.1'))
        self.assertFalse(_ipconfig_line_is_host_ipv4('DHCP Server . . . . . : 192.168.1.1'))

    def test_ipconfig_german_locale_host_ipv4(self) -> None:
        self.assertTrue(
            _ipconfig_line_is_host_ipv4('IPv4-Adresse. . . . . . . : 192.168.1.56')
        )
        self.assertTrue(_ipconfig_line_is_host_ipv4('IP-Adresse. . . . . . . : 192.168.1.56'))
        self.assertFalse(
            _ipconfig_line_is_host_ipv4('Standardgateway. . . . . . : 192.168.1.1')
        )
        self.assertFalse(
            _ipconfig_line_is_host_ipv4('DHCP-Server. . . . . . . . : 192.168.1.1')
        )
        self.assertFalse(
            _ipconfig_line_is_host_ipv4('Subnetzmaske. . . . . . . : 255.255.255.0')
        )

    def test_ipconfig_french_locale_host_ipv4(self) -> None:
        self.assertTrue(_ipconfig_line_is_host_ipv4('Adresse IPv4. . . . . . . : 192.168.1.56'))
        self.assertFalse(
            _ipconfig_line_is_host_ipv4('Passerelle par défaut. . . . : 192.168.1.1')
        )
        self.assertFalse(
            _ipconfig_line_is_host_ipv4('Serveur DHCP. . . . . . . . : 192.168.1.1')
        )
        self.assertFalse(
            _ipconfig_line_is_host_ipv4('Masque de sous-réseau. . . : 255.255.255.0')
        )

    def test_ipconfig_spanish_locale_host_ipv4(self) -> None:
        self.assertTrue(
            _ipconfig_line_is_host_ipv4('Dirección IPv4. . . . . . . : 192.168.1.56')
        )
        self.assertTrue(
            _ipconfig_line_is_host_ipv4('Direccion IPv4. . . . . . . : 192.168.1.56')
        )
        self.assertFalse(
            _ipconfig_line_is_host_ipv4(
                'Puerta de enlace predeterminada. . . : 192.168.1.1'
            )
        )
        self.assertFalse(
            _ipconfig_line_is_host_ipv4('Servidor DHCP. . . . . . . . : 192.168.1.1')
        )
        self.assertFalse(
            _ipconfig_line_is_host_ipv4('Máscara de subred. . . . . . : 255.255.255.0')
        )

    def test_ipconfig_adapter_headers_localized(self) -> None:
        cases = {
            'Ethernet adapter Ethernet:': 'Ethernet',
            'Wireless LAN adapter Wi-Fi:': 'Wi-Fi',
            'Ethernet-Adapter Ethernet:': 'Ethernet',
            'Drahtlos-LAN-Adapter WLAN:': 'WLAN',
            'Adaptador de Ethernet Ethernet:': 'Ethernet',
            'Adaptador de LAN inalámbrica Wi-Fi:': 'Wi-Fi',
            'Carte réseau sans fil Wi-Fi:': 'Wi-Fi',
            'Carte Ethernet Ethernet:': 'Ethernet',
            'Scheda Ethernet Ethernet:': 'Ethernet',
        }
        for header, expect in cases.items():
            self.assertTrue(
                _ipconfig_line_is_adapter_header(header), msg=header
            )
            self.assertEqual(
                _ipconfig_adapter_name_from_header(header), expect, msg=header
            )

        # Property lines must not be treated as adapter section headers.
        self.assertFalse(
            _ipconfig_line_is_adapter_header('IPv4 Address. . . . . . : 192.168.1.56')
        )
        self.assertFalse(
            _ipconfig_line_is_adapter_header('Adresse IPv4. . . . . . . : 192.168.1.56')
        )
        self.assertFalse(
            _ipconfig_line_is_adapter_header('Dirección IPv4. . . . . . : 192.168.1.56')
        )

    def test_get_my_ip_skips_apipa_when_dhcp_on_same_iface(self) -> None:
        routes = [
            (0, 0, '192.168.1.1', r'\\Device\\NPF_{GUID}', '169.254.151.57'),
            (0, 0, '192.168.1.1', r'\\Device\\NPF_{GUID}', '192.168.1.56'),
        ]
        with mock.patch('tools.utils.conf') as conf:
            conf.route.routes = routes
            conf.route.route.return_value = (0, '169.254.151.57', '192.168.1.1', r'\\Device\\NPF_{GUID}')
            ip = get_my_ip(r'\\Device\\NPF_{GUID}')
        self.assertEqual(ip, '192.168.1.56')

    def test_resolve_iface_my_ip_uses_cached_dhcp(self) -> None:
        iface = NetFace({
            'name': 'Wi-Fi',
            'guid': r'\\Device\\NPF_{GUID}',
            'ips': ['192.168.1.56'],
            'mac': 'AA:BB:CC:DD:EE:FF',
        })
        with mock.patch('tools.utils.get_my_ip', return_value='169.254.151.57'):
            with mock.patch('tools.utils.refresh_netface_live_ip'):
                ip = resolve_iface_my_ip(iface)
        self.assertEqual(ip, '192.168.1.56')


if __name__ == '__main__':
    unittest.main()
