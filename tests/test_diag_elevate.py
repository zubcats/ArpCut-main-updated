"""Admin PowerShell launch helpers for Logs diagnostics."""
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

from tools import diag_elevate as de  # noqa: E402


class TestWritePs1Runner(unittest.TestCase):
    def test_writes_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'ZubCut' / 't.ps1'
            de.write_ps1_runner(dest, 'Write-Host hi\n')
            raw = dest.read_bytes()
            self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
            self.assertIn(b'Write-Host hi', raw)


class TestLaunchPs1Elevated(unittest.TestCase):
    def test_already_admin_starts_powershell_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'x.ps1'
            script.write_text('Write-Host hi\n', encoding='utf-8')
            popen = mock.Mock(return_value=mock.Mock())
            with (
                mock.patch.object(sys, 'platform', 'win32'),
                mock.patch.object(de, '_already_admin', return_value=True),
                mock.patch.object(de.subprocess, 'Popen', popen),
            ):
                ok, msg = de.launch_ps1_elevated(script, tool_label='LAN path')
            self.assertTrue(ok)
            self.assertIn('LAN path', msg)
            popen.assert_called_once()
            args = popen.call_args.args[0]
            self.assertEqual(args[0], de.powershell_exe())
            self.assertIn('-File', args)
            self.assertEqual(args[-1], str(script))

    def test_not_admin_uses_elevate_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'x.ps1'
            script.write_text('Write-Host hi\n', encoding='utf-8')
            elevate = mock.Mock(return_value=True)
            with (
                mock.patch.object(sys, 'platform', 'win32'),
                mock.patch.object(de, '_already_admin', return_value=False),
            ):
                ok, msg = de.launch_ps1_elevated(
                    script, elevate=elevate, tool_label='Hotspot path'
                )
            self.assertTrue(ok)
            elevate.assert_called_once()
            self.assertIn('Hotspot path', msg)


if __name__ == '__main__':
    unittest.main()
