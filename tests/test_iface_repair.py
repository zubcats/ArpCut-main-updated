import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.ifaces import NetFace
from tools.utils import _is_bad_iface_display_name, repair_saved_iface_name


def _face(name: str, ip: str) -> NetFace:
    return NetFace({'name': name, 'guid': f'guid-{name}', 'mac': 'E8:4E:06:AB:C4:28', 'ips': [ip]})


class TestIfaceRepair(unittest.TestCase):
    def test_bad_description_label(self) -> None:
        self.assertTrue(_is_bad_iface_display_name('Description . . . . . . . . . . .'))

    @mock.patch('tools.utils.get_ifaces')
    @mock.patch('tools.utils.pick_best_live_iface')
    def test_repair_saved_iface_not_empty(self, mock_pick, mock_list) -> None:
        wifi = _face('Wi-Fi', '192.168.1.56')
        mock_pick.return_value = wifi
        mock_list.return_value = [wifi]
        with (
            mock.patch('tools.utils.invalidate_ifaces_cache'),
            mock.patch('tools.utils._iface_live_ipv4', return_value='192.168.1.56'),
            mock.patch('tools.utils.mac_address_is_usable', return_value=True),
        ):
            name = repair_saved_iface_name('Description . . . . . . . . . . .')
        self.assertEqual(name, 'Wi-Fi')

    def test_truncated_hotspot_index_is_bad_label(self) -> None:
        self.assertTrue(_is_bad_iface_display_name('10'))
        self.assertFalse(_is_bad_iface_display_name('Wi-Fi'))
