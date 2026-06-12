"""Default iface must not pick APIPA/disconnected adapters."""
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
from tools.utils import get_default_iface, repair_saved_iface_name, resolve_settings_iface_name


def _face(name: str, ip: str) -> NetFace:
    return NetFace({'name': name, 'guid': f'guid-{name}', 'mac': 'E8:4E:06:AB:C4:28', 'ips': [ip]})


class TestDefaultIfaceSelection(unittest.TestCase):
    @patch('tools.utils.get_ifaces')
    @patch('tools.utils.pick_best_live_iface')
    def test_get_default_iface_uses_pick_best(self, mock_pick, mock_list) -> None:
        wifi = _face('Wi-Fi', '192.168.1.56')
        mock_pick.return_value = wifi
        mock_list.return_value = [_face('Bluetooth Network Connection', '169.254.151.57'), wifi]
        with patch('tools.utils._iface_live_ipv4', return_value='192.168.1.56'):
            with patch('tools.utils.refresh_netface_live_ip'):
                got = get_default_iface()
        self.assertEqual(got.name, 'Wi-Fi')

    @patch('tools.utils.get_ifaces')
    @patch('tools.utils.pick_best_live_iface')
    def test_repair_saved_iface_maps_bluetooth_to_wifi(self, mock_pick, mock_list) -> None:
        wifi = _face('Wi-Fi', '192.168.1.56')
        mock_pick.return_value = wifi
        mock_list.return_value = [wifi]
        with patch('tools.utils.get_ifaces_cached', return_value=[]):
            with patch('tools.utils._iface_live_ipv4', side_effect=lambda i: '192.168.1.56' if i.name == 'Wi-Fi' else ''):
                with patch('tools.utils.invalidate_ifaces_cache'):
                    repaired = repair_saved_iface_name('Bluetooth Network Connection')
        self.assertEqual(repaired, 'Wi-Fi')

    @patch('tools.utils.get_ifaces_cached')
    @patch('tools.utils._iface_live_ipv4')
    def test_resolve_settings_requires_live_ip(self, mock_live, mock_cached) -> None:
        bt = _face('Bluetooth Network Connection', '169.254.151.57')
        wifi = _face('Wi-Fi', '192.168.1.56')
        mock_cached.return_value = [bt, wifi]

        def _live(iface):
            return '192.168.1.56' if iface.name == 'Wi-Fi' else ''

        mock_live.side_effect = _live
        self.assertEqual(resolve_settings_iface_name('Bluetooth Network Connection'), 'Wi-Fi')


if __name__ == '__main__':
    unittest.main()
