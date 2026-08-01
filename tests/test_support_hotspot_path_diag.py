"""Hotspot path diagnostic launcher (Logs → Hotspot path)."""
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

from tools import support_hotspot_path_diag as hpd  # noqa: E402


def _norm(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n').strip() + '\n'


class TestHotspotPathDiag(unittest.TestCase):
    def test_embedded_matches_repo_ps1(self) -> None:
        repo = _ROOT / 'tools' / 'ZubCut-Hotspot-Path-Diag.ps1'
        self.assertTrue(repo.is_file())
        self.assertEqual(
            _norm(repo.read_text(encoding='utf-8')),
            _norm(hpd._EMBEDDED_HOTSPOT_PATH_PS1),
        )
        self.assertIn('Test-MobileHotspotOn', hpd._EMBEDDED_HOTSPOT_PATH_PS1)
        self.assertIn('Clumsy hotspot', hpd._EMBEDDED_HOTSPOT_PATH_PS1)
        self.assertNotIn('Hotspot 192.168.137.x visible', hpd._EMBEDDED_HOTSPOT_PATH_PS1)

    def test_launch_elevates(self) -> None:
        elevate = mock.Mock(return_value=True)
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(sys, 'platform', 'win32'),
                mock.patch(
                    'tools.support_hotspot_path_diag.tempfile.gettempdir', return_value=tmp
                ),
            ):
                ok, msg = hpd.launch_hotspot_path_diag(elevate=elevate)
        self.assertTrue(ok)
        self.assertIn('Hotspot path', msg)
        elevate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
