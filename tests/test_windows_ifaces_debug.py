#!/usr/bin/env python3
"""
Windows interface debug wrapper — run manually, not via unittest discover.

  python tools/windows_ifaces_debug_diag.py
  python tests/test_windows_ifaces_debug.py
"""
from __future__ import annotations

import os
import runpy
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, 'tools', 'windows_ifaces_debug_diag.py')


class TestWindowsIfacesDebugDiagScript(unittest.TestCase):
    def test_diag_script_exists(self) -> None:
        self.assertTrue(os.path.isfile(_SCRIPT), f'Missing {_SCRIPT}')


if __name__ == '__main__':
    if len(sys.argv) == 1 and os.path.isfile(_SCRIPT):
        runpy.run_path(_SCRIPT, run_name='__main__')
    else:
        unittest.main()
