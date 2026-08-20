"""Windows command-output locale helpers (EN/DE/FR/ES)."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.win_locale import (
    arp_ifindex_pattern,
    arp_line_is_interface_header,
    fold_latin,
    ipconfig_adapter_name_from_header,
    ipconfig_gateway_findstr_command,
    ipconfig_line_is_adapter_header,
    ipconfig_line_is_host_ipv4,
    is_bad_iface_display_name,
    wlan_canonical_key,
    wlan_state_is_connected,
)


class TestWinLocale(unittest.TestCase):
    def test_fold_latin(self) -> None:
        self.assertEqual(fold_latin('Dirección'), 'direccion')
        self.assertEqual(fold_latin('Connecté'), 'connecte')

    def test_ipconfig_adapters(self) -> None:
        cases = {
            'Ethernet adapter Ethernet:': 'Ethernet',
            'Drahtlos-LAN-Adapter WLAN:': 'WLAN',
            'Adaptador de LAN inalámbrica Wi-Fi:': 'Wi-Fi',
            'Carte réseau sans fil Wi-Fi:': 'Wi-Fi',
        }
        for header, name in cases.items():
            self.assertTrue(ipconfig_line_is_adapter_header(header), header)
            self.assertEqual(ipconfig_adapter_name_from_header(header), name, header)

    def test_ipconfig_host_ipv4_locales(self) -> None:
        self.assertTrue(ipconfig_line_is_host_ipv4('IPv4 Address. . . : 192.168.1.1'))
        self.assertTrue(ipconfig_line_is_host_ipv4('IPv4-Adresse. . . : 192.168.1.1'))
        self.assertTrue(ipconfig_line_is_host_ipv4('Adresse IPv4. . . : 192.168.1.1'))
        self.assertTrue(ipconfig_line_is_host_ipv4('Dirección IPv4. . . : 192.168.1.1'))
        self.assertFalse(ipconfig_line_is_host_ipv4('Default Gateway . . : 192.168.1.1'))
        self.assertFalse(ipconfig_line_is_host_ipv4('Standardgateway. . : 192.168.1.1'))
        self.assertFalse(ipconfig_line_is_host_ipv4('Passerelle par défaut. : 192.168.1.1'))
        self.assertFalse(
            ipconfig_line_is_host_ipv4('Puerta de enlace predeterminada. : 192.168.1.1')
        )

    def test_gateway_findstr_covers_locales(self) -> None:
        cmd = ipconfig_gateway_findstr_command()
        self.assertIn('gateway', cmd)
        self.assertIn('Standardgateway', cmd)
        self.assertIn('passerelle', cmd)
        self.assertIn('enlace', cmd)

    def test_arp_headers(self) -> None:
        self.assertTrue(arp_line_is_interface_header('Interface: 192.168.1.10 --- 0x3'))
        self.assertTrue(arp_line_is_interface_header('Schnittstelle: 192.168.1.10 --- 0x3'))
        self.assertTrue(arp_line_is_interface_header('Interfaz: 192.168.1.10 --- 0x3'))
        self.assertTrue(arp_line_is_interface_header('Interface : 192.168.1.10 --- 0x3'))
        self.assertFalse(arp_line_is_interface_header('192.168.1.20          aa-bb-cc-dd-ee-ff'))

    def test_arp_ifindex_pattern(self) -> None:
        text = 'Schnittstelle: 192.168.137.1 --- 0x12\n  192.168.137.20 aa-bb-cc-dd-ee-ff'
        m = arp_ifindex_pattern('192.168.137.1').search(text)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1), 16), 0x12)

        # Still works when header word is missing (anchor on IP + --- 0x).
        text2 = '192.168.137.1 --- 0xa'
        m2 = arp_ifindex_pattern('192.168.137.1').search(text2)
        self.assertIsNotNone(m2)
        self.assertEqual(int(m2.group(1), 16), 0xA)

    def test_wlan_keys_and_state(self) -> None:
        self.assertEqual(wlan_canonical_key('Nom'), 'name')
        self.assertEqual(wlan_canonical_key('Nombre'), 'name')
        self.assertEqual(wlan_canonical_key('Zustand'), 'state')
        self.assertEqual(wlan_canonical_key('État'), 'state')
        self.assertEqual(wlan_canonical_key('Estado'), 'state')
        self.assertTrue(wlan_state_is_connected('connected', ssid='x'))
        self.assertTrue(wlan_state_is_connected('verbunden', ssid='x'))
        self.assertTrue(wlan_state_is_connected('Connecté', ssid='x'))
        self.assertTrue(wlan_state_is_connected('conectado', ssid='x'))
        self.assertFalse(wlan_state_is_connected('disconnected', ssid='x'))
        self.assertFalse(wlan_state_is_connected('getrennt', ssid='x'))
        # Unknown state word but SSID present → treat as associated.
        self.assertTrue(wlan_state_is_connected('weird', ssid='HomeWiFi'))

    def test_bad_iface_names_localized(self) -> None:
        self.assertTrue(is_bad_iface_display_name('connected'))
        self.assertTrue(is_bad_iface_display_name('verbunden'))
        self.assertTrue(is_bad_iface_display_name('connecté'))
        self.assertTrue(is_bad_iface_display_name('conectado'))
        self.assertFalse(is_bad_iface_display_name('Wi-Fi'))
        self.assertFalse(is_bad_iface_display_name('Ethernet 2'))
        self.assertTrue(is_bad_iface_display_name('10'))
        self.assertTrue(is_bad_iface_display_name('Interface-3'))


class TestWlanParseLocalized(unittest.TestCase):
    def test_parse_french_netsh_block(self) -> None:
        from tools.support_wifi_link_diag import parse_wlan_interfaces

        sample = """
There is 1 interface on the system:

    Nom                   : Wi-Fi
    Description           : Intel
    GUID                  : {abc}
    État                  : connecté
    SSID                  : Maison
    BSSID                 : aa:bb:cc:dd:ee:ff
    Authentification      : WPA2-Personal
    Canal                 : 36
    Bande                 : 5 GHz
"""
        rows = parse_wlan_interfaces(sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Wi-Fi')
        self.assertTrue(rows[0]['connected'])
        self.assertEqual(rows[0]['ssid'], 'Maison')
        self.assertEqual(rows[0]['channel'], 36)

    def test_parse_spanish_netsh_block(self) -> None:
        from tools.support_wifi_link_diag import parse_wlan_interfaces

        sample = """
    Nombre                : Wi-Fi
    Estado                : conectado
    SSID                  : Casa
    Autenticación         : WPA2-Personal
    Canal                 : 6
"""
        rows = parse_wlan_interfaces(sample)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['connected'])
        self.assertEqual(rows[0]['ssid'], 'Casa')


if __name__ == '__main__':
    unittest.main()
