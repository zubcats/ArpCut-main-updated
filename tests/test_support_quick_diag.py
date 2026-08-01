"""In-app Quick Network Diagnostic launcher (Logs → Network diagnostic)."""
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

from tools import support_quick_diag as sqd  # noqa: E402


def _norm_ps1(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n').strip() + '\n'


class TestSupportQuickDiag(unittest.TestCase):
    def test_embedded_matches_repo_ps1(self) -> None:
        repo = _ROOT / 'tools' / 'ZubCut-Quick-Network-Diag.ps1'
        self.assertTrue(repo.is_file(), f'missing {repo}')
        disk = _norm_ps1(repo.read_text(encoding='utf-8'))
        embedded = _norm_ps1(sqd._EMBEDDED_QUICK_DIAG_PS1)
        self.assertEqual(
            embedded,
            disk,
            'Update src/tools/support_quick_diag.py _EMBEDDED_QUICK_DIAG_PS1 '
            'to match tools/ZubCut-Quick-Network-Diag.ps1',
        )

    def test_materialize_writes_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch('tools.support_quick_diag.tempfile.gettempdir', return_value=tmp):
                path = sqd.materialize_quick_diag_ps1()
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, 'ZubCut-Quick-Network-Diag.ps1')
            body = path.read_text(encoding='utf-8')
            self.assertIn('ZubCut Quick Network Diagnostic', body)
            self.assertIn('SCREENSHOT THIS SUMMARY', body)
            self.assertIn('Npcap', body)

    def test_launch_non_windows(self) -> None:
        with mock.patch.object(sys, 'platform', 'linux'):
            ok, msg = sqd.launch_quick_network_diag_elevated()
        self.assertFalse(ok)
        self.assertIn('Windows-only', msg)

    def test_launch_elevates_powershell(self) -> None:
        elevate = mock.Mock(return_value=True)
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(sys, 'platform', 'win32'),
                mock.patch('tools.support_quick_diag.tempfile.gettempdir', return_value=tmp),
            ):
                ok, msg = sqd.launch_quick_network_diag_elevated(elevate=elevate)
        self.assertTrue(ok)
        self.assertIn('Admin PowerShell', msg)
        self.assertIn('ZubCut-Quick-Diag', msg)
        elevate.assert_called_once()
        exe, params = elevate.call_args.args[0], elevate.call_args.args[1]
        self.assertIn('powershell', exe.lower())
        self.assertIn('-ExecutionPolicy Bypass', params)
        self.assertIn('-File', params)
        self.assertIn('ZubCut-Quick-Network-Diag.ps1', params)

    def test_launch_uac_cancel(self) -> None:
        elevate = mock.Mock(return_value=False)
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(sys, 'platform', 'win32'),
                mock.patch('tools.support_quick_diag.tempfile.gettempdir', return_value=tmp),
            ):
                ok, msg = sqd.launch_quick_network_diag_elevated(elevate=elevate)
        self.assertFalse(ok)
        self.assertIn('UAC', msg)


class TestLogsDiagButtonWiring(unittest.TestCase):
    def test_logs_window_has_network_diag_button(self) -> None:
        path = os.path.join(_SRC, 'gui', 'logs_window.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn("setObjectName('logsDiagPanel')", src)
        self.assertIn("setObjectName('logsDiagNetworkBtn')", src)
        self.assertIn('Network diagnostic', src)
        self.assertIn('def _run_network_diagnostic', src)
        self.assertIn('launch_quick_network_diag_elevated', src)
        self.assertNotIn('Diagnostic tools — coming soon', src)

    def test_diag_button_theme_is_charcoal(self) -> None:
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('QFrame#logsDiagPanel', src)
        self.assertIn('QPushButton#logsDiagNetworkBtn', src)
        block = src[
            src.index('QFrame#logsDiagPanel') : src.index(
                'QPushButton#logsDiagNetworkBtn:pressed'
            )
        ]
        self.assertNotIn('#19232D', block)
        self.assertNotIn('#1A72BB', block)


if __name__ == '__main__':
    unittest.main()
