"""WinDivert stale kernel service detection (error 3)."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.ics_windivert_shaper import _windivert_normalized_path


class TestWinDivertServiceRepair(unittest.TestCase):
    def test_normalize_registry_image_path(self) -> None:
        raw = r'\??\C:\Temp\Rar$EXa\WinDivert64.sys'
        norm = _windivert_normalized_path(raw)
        self.assertTrue(norm.endswith(os.path.normcase('WinDivert64.sys')))
        self.assertIn('rar', norm.lower())

    def test_normalize_plain_path(self) -> None:
        p = _windivert_normalized_path(r'C:\ZubCut\windivert\WinDivert64.sys')
        self.assertEqual(
            p,
            os.path.normcase(os.path.abspath(r'C:\ZubCut\windivert\WinDivert64.sys')),
        )


if __name__ == '__main__':
    unittest.main()
