#!/usr/bin/env python3
"""
One-way kill interactive demo wrapper — run manually, not via unittest discover.

  python tools/oneway_kill_diag.py <victim_ip>
  python tests/test_oneway_kill.py <victim_ip>
"""
from __future__ import annotations

import os
import runpy
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, 'tools', 'oneway_kill_diag.py')


class TestOnewayKillDiagScript(unittest.TestCase):
    def test_diag_script_exists(self) -> None:
        self.assertTrue(os.path.isfile(_SCRIPT), f'Missing {_SCRIPT}')


if __name__ == '__main__':
    if len(sys.argv) >= 2 and os.path.isfile(_SCRIPT):
        # Preserve CLI: pass victim IP through to the diagnostic.
        sys.argv = [_SCRIPT, *sys.argv[1:]]
        runpy.run_path(_SCRIPT, run_name='__main__')
    elif len(sys.argv) == 1 and os.path.isfile(_SCRIPT):
        runpy.run_path(_SCRIPT, run_name='__main__')
    else:
        unittest.main()
