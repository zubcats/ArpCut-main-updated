"""ICS hotspot victims must not be re-ARP-killed on rescan."""
from __future__ import annotations

import inspect
import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestKillerRekillIcs(unittest.TestCase):
    def test_rekill_stored_skips_hotspot_subnet(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        block = src[src.index('def rekill_stored'): src.index('def one_way_kill')]
        self.assertIn('victim_on_clumsy_ics_subnet', block)
        self.assertIn('continue', block)


if __name__ == '__main__':
    unittest.main()
