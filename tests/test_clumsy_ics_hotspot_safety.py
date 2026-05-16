"""Clumsy ICS: hotspot mode must not tear down Mobile Hotspot."""

from __future__ import annotations

import inspect
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import clumsy_ics as ics


class ClumsyHotspotSafetyTests(unittest.TestCase):
    def test_enable_script_hotspot_exits_without_apply_ics(self) -> None:
        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn("$ZubcutTopology = '{topo}'", src)
        self.assertIn('ZubCut will not reset ICS in hotspot mode', src)
        # Hotspot branch must throw before ethernet-only netsh stop (after hotspot block).
        hotspot_idx = src.index("if ($ZubcutTopology -eq 'hotspot')")
        netsh_idx = src.index('netsh wlan stop hostednetwork', hotspot_idx)
        throw_idx = src.index('will not reset ICS in hotspot mode', hotspot_idx)
        self.assertLess(throw_idx, netsh_idx)

    def test_maybe_repair_skips_when_no_state_file(self) -> None:
        path = ics.clumsy_ics_state_path()
        had = os.path.isfile(path)
        try:
            if had:
                os.remove(path)
            ics.maybe_repair_stale_clumsy_ics_on_startup()
        finally:
            if had and not os.path.isfile(path):
                pass


if __name__ == '__main__':
    unittest.main()
