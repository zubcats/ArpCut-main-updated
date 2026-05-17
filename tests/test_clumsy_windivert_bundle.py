"""Clumsy / WinDivert bundle detection (installer layout)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import clumsy_inline as inline


class TestClumsyWinDivertBundle(unittest.TestCase):
    def test_windivert_bundled_next_to_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wd = os.path.join(tmp, 'windivert')
            os.makedirs(wd)
            open(os.path.join(wd, 'WinDivert.dll'), 'wb').close()
            open(os.path.join(wd, 'WinDivert64.sys'), 'wb').close()
            with patch.object(sys, 'frozen', True, create=True):
                with patch.object(sys, 'executable', os.path.join(tmp, 'ZubCut.exe')):
                    self.assertTrue(inline.windivert_bundled_next_to_app())
                    self.assertTrue(inline.windivert_driver_installed())

    def test_clumsy_bundle_incomplete_when_flag_without_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            flag = os.path.join(tmp, inline.CLUMSY_BUNDLE_FLAG_NAME)
            with open(flag, 'w', encoding='utf-8') as fh:
                fh.write('1')
            with patch.object(sys, 'frozen', True, create=True):
                with patch.object(sys, 'executable', os.path.join(tmp, 'ZubCut.exe')):
                    with patch.object(
                        inline, 'clumsy_bundle_flag_path', return_value=flag
                    ):
                        self.assertTrue(inline.clumsy_bundle_offered())
                        self.assertTrue(inline.clumsy_bundle_incomplete())
                        self.assertFalse(inline.clumsy_runtime_ready())


if __name__ == '__main__':
    unittest.main()
