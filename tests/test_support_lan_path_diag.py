"""LAN path diagnostic launcher (Logs → LAN path)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tools import support_lan_path_diag as lpd  # noqa: E402


def _norm(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n').strip() + '\n'


class TestLanPathDiag(unittest.TestCase):
    def test_embedded_matches_repo_ps1(self) -> None:
        repo = _ROOT / 'tools' / 'ZubCut-Lan-Path-Diag.ps1'
        self.assertTrue(repo.is_file())
        self.assertEqual(_norm(repo.read_text(encoding='utf-8')), _norm(lpd._EMBEDDED_LAN_PATH_PS1))
        self.assertIn('Active path: LAN Kill', lpd._EMBEDDED_LAN_PATH_PS1)
        self.assertIn('Gateway MAC known', lpd._EMBEDDED_LAN_PATH_PS1)

    def test_materialize_outside_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch('tools.support_lan_path_diag.tempfile.gettempdir', return_value=tmp):
                path = lpd.materialize_lan_path_ps1()
            self.assertTrue(path.is_file())
            self.assertEqual(path.parent.name, 'ZubCut')
            self.assertNotIn('ZubCut Diagnostics', str(path))

    def test_launch_elevates(self) -> None:
        elevate = mock.Mock(return_value=True)
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(sys, 'platform', 'win32'),
                mock.patch('tools.support_lan_path_diag.tempfile.gettempdir', return_value=tmp),
            ):
                ok, msg = lpd.launch_lan_path_diag(elevate=elevate)
        self.assertTrue(ok)
        self.assertIn('LAN path', msg)
        elevate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
