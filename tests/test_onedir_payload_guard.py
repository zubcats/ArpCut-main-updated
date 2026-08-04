"""Guards so updates cannot ship / leave ZubCut without _internal\\python311.dll."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
_TOOLS = os.path.join(_ROOT, 'tools')
for _p in (_SRC, _TOOLS, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from verify_onedir_payload import verify_onedir  # noqa: E402
from tools.updater_core import (  # noqa: E402
    _write_update_waiter_ps1,
    install_payload_ok,
    launch_installer,
)


class TestVerifyOnedirPayload(unittest.TestCase):
    def test_ok_when_exe_and_dll_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = os.path.join(td, 'ZubCut')
            os.makedirs(os.path.join(root, '_internal'))
            with open(os.path.join(root, 'ZubCut.exe'), 'wb') as fp:
                fp.write(b'MZ' + b'\0' * 100)
            with open(os.path.join(root, '_internal', 'python311.dll'), 'wb') as fp:
                fp.write(b'X' * 120_000)
            self.assertEqual(verify_onedir(root), [])

    def test_errors_when_internal_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = os.path.join(td, 'ZubCut')
            os.makedirs(root)
            with open(os.path.join(root, 'ZubCut.exe'), 'wb') as fp:
                fp.write(b'MZ')
            errs = verify_onedir(root)
            self.assertTrue(any('_internal' in e for e in errs))


class TestInstallPayloadOk(unittest.TestCase):
    def test_false_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(install_payload_ok(td))

    def test_true_when_dll_large_enough(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, '_internal'))
            with open(os.path.join(td, '_internal', 'python311.dll'), 'wb') as fp:
                fp.write(b'Y' * 100_000)
            self.assertTrue(install_payload_ok(td))


class TestLaunchInstallerWaiter(unittest.TestCase):
    def test_writes_waiter_checking_python_dll(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            installer = os.path.join(td, 'setup.exe')
            with open(installer, 'wb') as fp:
                fp.write(b'MZ')
            ps1 = _write_update_waiter_ps1(
                installer_path=installer,
                app_dir=r'C:\Program Files\ZubCut',
                flags=['/SILENT', '/NORESTART'],
            )
            with open(ps1, encoding='utf-8') as fp:
                text = fp.read()
            self.assertIn('python311.dll', text)
            self.assertIn('ZubCut Update Failed', text)
            self.assertIn('/SILENT', text)

    def test_launch_installer_prefers_detached_waiter_on_windows(self) -> None:
        if not sys.platform.startswith('win'):
            self.skipTest('Windows-only')
        with tempfile.TemporaryDirectory() as td:
            installer = os.path.join(td, 'setup.exe')
            with open(installer, 'wb') as fp:
                fp.write(b'MZ')
            calls: list = []

            def _popen(cmd, **kwargs):
                calls.append((cmd, kwargs))

                class _P:
                    pid = 1

                return _P()

            with patch('tools.updater_core.subprocess.Popen', side_effect=_popen), patch(
                'tools.clumsy_inline.clumsy_bundle_offered',
                return_value=False,
            ):
                launch_installer(installer, no_ui=False)
            self.assertEqual(len(calls), 1)
            cmd, _kwargs = calls[0]
            self.assertEqual(cmd[0], 'powershell.exe')
            self.assertIn('-File', cmd)


class TestInnoSetupGuards(unittest.TestCase):
    def test_zubcut_iss_restores_internal_on_missing_dll(self) -> None:
        with open(
            os.path.join(_ROOT, 'installer', 'ZubCut.iss'), encoding='utf-8'
        ) as fp:
            iss = fp.read()
        self.assertIn('PrepareToInstall', iss)
        self.assertIn('_internal.bak_zubcut', iss)
        self.assertIn('python311.dll', iss)
        self.assertIn('RestoreInternalBackupIfNeeded', iss)
        # Hard delete without backup must not return.
        self.assertNotIn(
            'Type: filesandordirs; Name: "{app}\\_internal"',
            iss,
        )
        # Post-install must stay elevated (Npcap AdminOnly).
        self.assertIn('runascurrentuser', iss)
        self.assertRegex(
            iss,
            r'Flags:\s*nowait postinstall shellexec runascurrentuser',
        )


if __name__ == '__main__':
    unittest.main()
