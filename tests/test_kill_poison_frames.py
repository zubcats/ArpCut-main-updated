"""LAN Kill poison frames must stay unicast (no Wi‑Fi gateway broadcast)."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestKillPoisonFrames(unittest.TestCase):
    def test_poison_frames_source_has_no_wifi_broadcast(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        block = src[src.index('def _poison_frames'): src.index('def _poison_arp_now')]
        self.assertNotIn('ff:ff:ff:ff:ff:ff', block)
        self.assertIn('Unicast ARP poison only', block)
        self.assertIn("dst=victim['mac']", block)
        self.assertIn("dst=self.router['mac']", block)


if __name__ == '__main__':
    unittest.main()
