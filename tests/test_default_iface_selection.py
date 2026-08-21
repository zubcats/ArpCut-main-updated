"""Default iface must not pick APIPA/disconnected adapters."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.ifaces import NetFace
from tools.utils import get_default_iface, repair_saved_iface_name, resolve_settings_iface_name


def _face(name: str, ip: str) -> NetFace:
    return NetFace({'name': name, 'guid': f'guid-{name}', 'mac': 'E8:4E:06:AB:C4:28', 'ips': [ip]})


class TestDefaultIfaceSelection(unittest.TestCase):
    @mock.patch('tools.utils.get_ifaces')
    @mock.patch('tools.utils.pick_best_live_iface')
    def test_get_default_iface_uses_pick_best(self, mock_pick, mock_list) -> None:
        wifi = _face('Wi-Fi', '192.168.1.56')
        mock_pick.return_value = wifi
        mock_list.return_value = [_face('Bluetooth Network Connection', '169.254.151.57'), wifi]
        with mock.patch('tools.utils._iface_live_ipv4', return_value='192.168.1.56'):
            with mock.patch('tools.utils.refresh_netface_live_ip'):
                got = get_default_iface()
        self.assertEqual(got.name, 'Wi-Fi')

    @mock.patch('tools.utils.get_ifaces')
    @mock.patch('tools.utils.pick_best_live_iface')
    def test_repair_keeps_valid_wifi_when_ethernet_is_default(self, mock_pick, mock_list) -> None:
        eth = _face('Ethernet 2', '192.168.1.110')
        wifi = _face('Wi-Fi', '192.168.1.56')
        mock_list.return_value = [eth, wifi]
        mock_pick.return_value = eth
        with (
            mock.patch('tools.utils.invalidate_ifaces_cache'),
            mock.patch('tools.utils._iface_live_ipv4', side_effect=lambda i: i.ip),
            mock.patch('tools.utils.mac_address_is_usable', return_value=True),
        ):
            repaired = repair_saved_iface_name('Wi-Fi')
        self.assertEqual(repaired, 'Wi-Fi')

    @mock.patch('tools.utils.get_ifaces')
    @mock.patch('tools.utils.pick_best_live_iface')
    def test_repair_saved_iface_maps_bluetooth_to_wifi(self, mock_pick, mock_list) -> None:
        wifi = _face('Wi-Fi', '192.168.1.56')
        mock_pick.return_value = wifi
        mock_list.return_value = [wifi]
        with mock.patch('tools.utils.get_ifaces_cached', return_value=[]):
            with mock.patch('tools.utils._iface_live_ipv4', side_effect=lambda i: '192.168.1.56' if i.name == 'Wi-Fi' else ''):
                with mock.patch('tools.utils.invalidate_ifaces_cache'):
                    repaired = repair_saved_iface_name('Bluetooth Network Connection')
        self.assertEqual(repaired, 'Wi-Fi')

    @mock.patch('tools.utils.get_ifaces_cached')
    @mock.patch('tools.utils._iface_live_ipv4')
    def test_resolve_keeps_saved_wifi_name(self, mock_live, mock_cached) -> None:
        bt = _face('Bluetooth Network Connection', '169.254.151.57')
        wifi = _face('Wi-Fi', '192.168.1.56')
        eth = _face('Ethernet 2', '192.168.1.110')
        mock_cached.return_value = [bt, wifi, eth]

        def _live(iface):
            return {'Wi-Fi': '192.168.1.56', 'Ethernet 2': '192.168.1.110'}.get(iface.name, '')

        mock_live.side_effect = _live
        self.assertEqual(resolve_settings_iface_name('Wi-Fi'), 'Wi-Fi')

    @mock.patch('tools.utils.get_ifaces')
    @mock.patch('tools.utils.pick_best_live_iface')
    def test_repair_maps_hotspot_nic_to_wifi_when_clumsy_off(self, mock_pick, mock_list) -> None:
        wifi = _face('Wi-Fi', '192.168.1.56')
        lac = _face('Local Area Connection* 10', '192.168.137.1')
        mock_list.return_value = [lac, wifi]
        mock_pick.return_value = wifi
        with (
            mock.patch('tools.utils.invalidate_ifaces_cache'),
            mock.patch('tools.utils._softap_bind_allowed', return_value=False),
            mock.patch(
                'tools.utils._iface_live_ipv4',
                side_effect=lambda i: '192.168.1.56' if i.name == 'Wi-Fi' else '',
            ),
            mock.patch('tools.utils.mac_address_is_usable', return_value=True),
        ):
            repaired = repair_saved_iface_name('Local Area Connection* 10')
        self.assertEqual(repaired, 'Wi-Fi')

    def test_live_ipv4_ignores_softap_when_clumsy_off(self) -> None:
        from tools.utils import _iface_live_ipv4

        lac = _face('Local Area Connection* 10', '192.168.137.1')
        with mock.patch('tools.utils._softap_bind_allowed', return_value=False):
            self.assertEqual(_iface_live_ipv4(lac), '')

    def test_live_ipv4_keeps_softap_when_clumsy_on(self) -> None:
        from tools.utils import _iface_live_ipv4

        lac = _face('Local Area Connection* 10', '192.168.137.1')
        with (
            mock.patch('tools.utils._softap_bind_allowed', return_value=True),
            mock.patch('tools.utils.get_my_ip', return_value='192.168.137.1'),
        ):
            self.assertEqual(_iface_live_ipv4(lac), '192.168.137.1')

    @mock.patch('tools.utils.get_ifaces')
    @mock.patch('tools.utils.pick_best_live_iface')
    def test_repair_maps_truncated_hotspot_index_to_wifi(self, mock_pick, mock_list) -> None:
        wifi = _face('Wi-Fi', '192.168.1.56')
        mock_list.return_value = [wifi]
        mock_pick.return_value = wifi
        with (
            mock.patch('tools.utils.invalidate_ifaces_cache'),
            mock.patch('tools.utils._softap_bind_allowed', return_value=False),
            mock.patch('tools.utils._iface_live_ipv4', return_value='192.168.1.56'),
            mock.patch('tools.utils.mac_address_is_usable', return_value=True),
        ):
            repaired = repair_saved_iface_name('10')
        self.assertEqual(repaired, 'Wi-Fi')

    def test_settings_combo_hides_hotspot_leftover_when_clumsy_off(self) -> None:
        from tools.utils import ifaces_for_settings_combo

        wifi = _face('Wi-Fi', '192.168.1.56')
        lac = _face('Local Area Connection* 10', '0.0.0.0')
        with mock.patch('tools.utils._softap_bind_allowed', return_value=False):
            shown = ifaces_for_settings_combo([lac, wifi])
        self.assertEqual([i.name for i in shown], ['Wi-Fi'])

    def test_ambiguous_radio_mac_prefers_wifi_lan_over_hotspot_leftover(self) -> None:
        from tools.utils import _mac_match_ipconfig_adapter

        shared = 'E8:4E:06:AB:C4:28'
        interface_map = {
            'Wi-Fi': {'ip': '192.168.1.56', 'mac': shared},
            'Local Area Connection* 10': {'ip': '0.0.0.0', 'mac': shared},
        }
        with mock.patch('tools.utils._softap_bind_allowed', return_value=False):
            name, info = _mac_match_ipconfig_adapter(shared, interface_map)
        self.assertEqual(name, 'Wi-Fi')
        self.assertEqual(info['ip'], '192.168.1.56')

    def test_same_ip_prefers_wifi_over_softap(self) -> None:
        from tools.utils import _better_iface_for_same_ip

        wifi = _face('Wi-Fi', '192.168.1.56')
        lac = _face('Local Area Connection* 10', '192.168.1.56')
        self.assertEqual(_better_iface_for_same_ip(lac, wifi).name, 'Wi-Fi')
        self.assertEqual(_better_iface_for_same_ip(wifi, lac).name, 'Wi-Fi')

    def test_resolve_iface_drops_stale_hotspot_ip_when_clumsy_off(self) -> None:
        from tools.utils import resolve_iface_my_ip

        lac = _face('Local Area Connection* 10', '192.168.137.1')
        with (
            mock.patch('tools.utils._softap_bind_allowed', return_value=False),
            mock.patch('tools.utils.get_my_ip', return_value='192.168.137.1'),
        ):
            self.assertEqual(resolve_iface_my_ip(lac), '')

    @mock.patch('tools.utils.get_ifaces_cached')
    @mock.patch('tools.utils.pick_best_live_iface')
    def test_resolve_remaps_raw_guid_to_wifi(self, mock_pick, mock_cached) -> None:
        wifi = _face('Wi-Fi', '192.168.1.56')
        mock_cached.return_value = [wifi]
        mock_pick.return_value = wifi
        with mock.patch('tools.utils._iface_live_ipv4', return_value='192.168.1.56'):
            self.assertEqual(
                resolve_settings_iface_name('A3737896-1E6A-4AC6-9FEC-0E20BF3F15DC'),
                'Wi-Fi',
            )

    def test_pick_windows_gateway_skips_hotspot_and_multicast(self) -> None:
        from tools.utils import _gateways_from_ipconfig_text, _pick_windows_gateway

        text = """
Wireless LAN adapter Wi-Fi:

   IPv4 Address. . . . . . . . . . . : 192.168.1.56
   Default Gateway . . . . . . . . . : 192.168.1.1

Ethernet adapter Local Area Connection* 10:

   IPv4 Address. . . . . . . . . . . : 192.168.137.1
   Default Gateway . . . . . . . . . : 0.0.0.0
"""
        rows = _gateways_from_ipconfig_text(text)
        with mock.patch('tools.utils._softap_bind_allowed', return_value=False):
            gw = _pick_windows_gateway(rows, iface_hint=r'\\Device\\NPF_{A373}', src_ip='')
        self.assertEqual(gw, '192.168.1.1')

    def test_pick_windows_gateway_reads_ipv4_on_line_after_ipv6(self) -> None:
        from tools.utils import _gateways_from_ipconfig_text, _pick_windows_gateway

        text = """
Wireless LAN adapter Wi-Fi:

   IPv4 Address. . . . . . . . . . . : 192.168.1.56
   Default Gateway . . . . . . . . . : fe80::7624:9fff:fe37:1eec%8
                                       192.168.1.1
"""
        rows = _gateways_from_ipconfig_text(text)
        self.assertEqual(rows, [('Wi-Fi', '192.168.1.56', '192.168.1.1')])
        self.assertEqual(_pick_windows_gateway(rows, iface_hint='Wi-Fi', src_ip='192.168.1.56'), '192.168.1.1')

    def test_merge_windows_live_ifaces_skips_unlisted_guid_when_npcap_empty(self) -> None:
        from tools.utils import _merge_windows_live_ifaces

        interface_map = {
            'Wi-Fi': {
                'ip': '192.168.1.56',
                'mac': 'E8:4E:06:AB:C4:28',
                'guid': None,
            },
            'Ethernet 2': {
                'ip': '0.0.0.0',
                'mac': '6C:2B:59:D1:F3:96',
                'guid': None,
            },
        }
        with (
            mock.patch(
                'tools.utils._windows_adapter_friendly_by_guid',
                return_value={'{5B106E08-62B0-4A70-B2AC-AEDD80B5B255}': 'Wi-Fi'},
            ),
            mock.patch('tools.utils._npcap_listed_guids', return_value=set()),
        ):
            faces = _merge_windows_live_ifaces([], interface_map, listed_guids=set())
        self.assertEqual(faces, [])

    def test_merge_overlays_live_ip_without_replacing_npcap_guid(self) -> None:
        from tools.utils import _merge_windows_live_ifaces

        ghost = _face('Wi-Fi', '169.254.151.57')
        ghost.guid = r'\Device\NPF_{A3737896-1E6A-4AC6-9FEC-0E20BF3F15DC}'
        interface_map = {
            'Wi-Fi': {
                'ip': '192.168.1.56',
                'mac': 'E8:4E:06:AB:C4:28',
                'guid': None,
            },
        }
        with (
            mock.patch(
                'tools.utils._windows_adapter_friendly_by_guid',
                return_value={'{5B106E08-62B0-4A70-B2AC-AEDD80B5B255}': 'Wi-Fi'},
            ),
            mock.patch(
                'tools.utils._npcap_listed_guids',
                return_value={'A3737896-1E6A-4AC6-9FEC-0E20BF3F15DC'},
            ),
        ):
            faces = _merge_windows_live_ifaces(
                [ghost],
                interface_map,
                listed_guids={'A3737896-1E6A-4AC6-9FEC-0E20BF3F15DC'},
            )
        self.assertEqual(len(faces), 1)
        self.assertEqual(faces[0].ip, '192.168.1.56')
        self.assertIn('A3737896', faces[0].guid.upper())
        self.assertNotIn('5B106E08', faces[0].guid.upper())

    def test_npcap_tokens_skip_unlisted_windows_guid(self) -> None:
        from tools.utils import npcap_iface_tokens

        fake = r'\Device\NPF_{5B106E08-62B0-4A70-B2AC-AEDD80B5B255}'
        listed = r'\Device\NPF_{A3737896-1E6A-4AC6-9FEC-0E20BF3F15DC}'
        face = _face('Wi-Fi', '192.168.1.56')
        face.guid = fake
        with mock.patch('tools.utils.get_if_list', return_value=[listed]):
            toks = npcap_iface_tokens(face)
        self.assertNotIn(fake, toks)
        self.assertIn('Wi-Fi', toks)


    def test_live_ipv4_uses_overlay_when_pcap_ip_is_apipa(self) -> None:
        from tools.utils import _iface_live_ipv4

        wifi = _face('Wi-Fi', '192.168.1.56')
        with mock.patch('tools.utils.get_my_ip', return_value='169.254.151.57'):
            self.assertEqual(_iface_live_ipv4(wifi), '192.168.1.56')

    def test_device_list_noise_helpers(self) -> None:
        from tools.utils import ipv4_is_device_list_noise, mac_is_device_list_noise

        self.assertTrue(ipv4_is_device_list_noise('224.0.0.22'))
        self.assertTrue(ipv4_is_device_list_noise('224.0.0.251'))
        self.assertTrue(ipv4_is_device_list_noise('0.0.0.0'))
        self.assertFalse(ipv4_is_device_list_noise('192.168.1.160'))
        self.assertTrue(mac_is_device_list_noise('01:00:5e:00:00:16'))
        self.assertFalse(mac_is_device_list_noise('74:24:9f:37:1e:ec'))


if __name__ == '__main__':
    unittest.main()
