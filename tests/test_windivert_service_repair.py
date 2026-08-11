"""WinDivert stale kernel service detection (error 3)."""
from __future__ import annotations

import inspect
import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import ics_windivert_shaper as wd
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

    def test_sc_stop_delete_timeout_capped(self) -> None:
        src = inspect.getsource(wd._windivert_sc_stop_and_delete)
        self.assertIn('timeout=3', src)
        self.assertNotIn('timeout=15', src)

    def test_repair_is_session_deduped(self) -> None:
        src = inspect.getsource(wd._windivert_repair_stale_service)
        self.assertIn('_WD_SERVICE_REPAIR_DONE', src)
        self.assertIn('already repaired this session', src)

    def test_prewarm_windivert_driver_exported(self) -> None:
        self.assertTrue(callable(wd.prewarm_windivert_driver))
        src = inspect.getsource(wd.prewarm_windivert_driver)
        self.assertIn('_windivert_materialize_paths', src)
        self.assertIn('_open_windivert_handles', src)


if __name__ == '__main__':
    unittest.main()
