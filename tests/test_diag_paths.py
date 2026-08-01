"""Desktop\\ZubCut Diagnostics folder helpers."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tools import diag_paths as dp  # noqa: E402


class TestDiagPaths(unittest.TestCase):
    def test_ensure_creates_folder_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            desk = Path(tmp) / 'Desktop'
            desk.mkdir()
            with mock.patch.object(dp, 'desktop_dir', return_value=desk):
                first = dp.ensure_zubcut_diagnostics_dir()
                second = dp.ensure_zubcut_diagnostics_dir()
            self.assertEqual(first, desk / 'ZubCut Diagnostics')
            self.assertEqual(first, second)
            self.assertTrue(first.is_dir())

    def test_desktop_dir_prefers_shell_api_on_windows(self) -> None:
        if not sys.platform.startswith('win'):
            # On Linux CI: fall back path still returns a Path.
            self.assertIsInstance(dp.desktop_dir(), Path)
            return
        desk = dp.desktop_dir()
        self.assertTrue(desk.is_dir())

    def test_quick_ps1_writes_reports_to_diagnostics_folder(self) -> None:
        path = _ROOT / 'tools' / 'ZubCut-Quick-Network-Diag.ps1'
        src = path.read_text(encoding='utf-8')
        self.assertIn("Join-Path $desktop 'ZubCut Diagnostics'", src)
        self.assertIn('ZubCut-Quick-Diag-', src)
        # Runner itself is not copied into that folder by the PS1.
        self.assertNotIn("Copy-Item", src)


if __name__ == '__main__':
    unittest.main()
