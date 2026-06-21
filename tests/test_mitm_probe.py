"""MITM effectiveness probe helpers."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.ifaces import NetFace
from tools.mitm_probe import iface_is_wireless, mitm_path_warning


class TestMitmProbe(unittest.TestCase):
    def test_iface_is_wireless(self) -> None:
        wifi = NetFace({'name': 'Wi-Fi', 'guid': 'g', 'mac': 'aa:bb:cc:dd:ee:ff', 'ips': ['192.168.1.56']})
        eth = NetFace({'name': 'Ethernet', 'guid': 'g', 'mac': 'aa:bb:cc:dd:ee:ff', 'ips': ['192.168.1.56']})
        self.assertTrue(iface_is_wireless(wifi))
        self.assertFalse(iface_is_wireless(eth))

    def test_wifi_warning_mentions_topology(self) -> None:
        wifi = NetFace({'name': 'Wi-Fi', 'guid': 'g', 'mac': 'aa:bb:cc:dd:ee:ff', 'ips': ['192.168.1.56']})
        msg = mitm_path_warning(wifi, '192.168.1.248')
        self.assertIn('Wi‑Fi', msg)
        self.assertIn('192.168.1.248', msg)


if __name__ == '__main__':
    unittest.main()
