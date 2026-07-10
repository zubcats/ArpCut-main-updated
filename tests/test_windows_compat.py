#!/usr/bin/env python3
"""
Windows compatibility diagnostic — run manually, not via unittest discover.

  python tests/test_windows_compat.py

This file is intentionally not a unittest module: module-level sys.exit() would
break ``unittest discover``. Keep the real script under tools/.
"""
from __future__ import annotations

import os
import runpy
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, 'tools', 'windows_compat_diag.py')


class TestWindowsCompatDiagScript(unittest.TestCase):
    def test_diag_script_exists(self) -> None:
        self.assertTrue(
            os.path.isfile(_SCRIPT),
            f'Missing {_SCRIPT} — move the manual diagnostic there',
        )


if __name__ == '__main__':
    # Preserve old CLI: python tests/test_windows_compat.py runs the diagnostic.
    if len(sys.argv) == 1 and os.path.isfile(_SCRIPT):
        runpy.run_path(_SCRIPT, run_name='__main__')
    else:
        unittest.main()
