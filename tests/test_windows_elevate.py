"""Windows elevation guard (no real UAC in CI)."""
import os
import sys
import unittest
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools import utils_gui as ug


class TestWindowsElevate(unittest.TestCase):
    def tearDown(self):
        os.environ.pop('ZUBCUT_SKIP_ELEVATE', None)

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_skip_env_does_not_shell_execute(self):
        os.environ['ZUBCUT_SKIP_ELEVATE'] = '1'
        with patch.object(ug, 'is_admin', return_value=False):
            with patch.object(ug.ctypes.windll.shell32, 'ShellExecuteW') as se:
                self.assertTrue(ug.ensure_windows_elevated())
                se.assert_not_called()

    def test_non_windows_always_ok(self):
        with patch.object(ug.sys, 'platform', 'linux'):
            self.assertTrue(ug.ensure_windows_elevated())

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_already_admin_no_relaunch(self):
        with patch.object(ug, 'is_admin', return_value=True):
            with patch.object(ug.ctypes.windll.shell32, 'ShellExecuteW') as se:
                self.assertTrue(ug.ensure_windows_elevated())
                se.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_uac_declined_returns_false(self):
        with patch.object(ug, 'is_admin', return_value=False):
            with patch.object(ug, '_elevate_handoff_requested', return_value=False):
                with patch.object(ug.ctypes.windll.shell32, 'ShellExecuteW', return_value=5):
                    with patch.object(ug.ctypes.windll.user32, 'MessageBoxW'):
                        self.assertFalse(ug.ensure_windows_elevated())

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_handoff_does_not_prompt_again(self):
        with patch.object(ug, 'is_admin', return_value=False):
            with patch.object(ug, '_elevate_handoff_requested', return_value=True):
                with patch.object(ug.ctypes.windll.shell32, 'ShellExecuteW') as se:
                    with patch.object(ug.ctypes.windll.user32, 'MessageBoxW'):
                        self.assertFalse(ug.ensure_windows_elevated())
                se.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_restart_zubcut_uses_runas_when_not_admin(self):
        with patch.object(ug, 'is_admin', return_value=False):
            with patch.object(ug, '_windows_relaunch_command', return_value=('ZubCut.exe', '', r'C:\ZubCut')):
                with patch.object(ug, '_zubcut_relaunch_argv', return_value=[]):
                    with patch.object(ug, 'spawn_windows_elevated', return_value=True) as spawn:
                        with patch.object(ug, 'release_zubcut_single_instance') as rel:
                            self.assertTrue(ug.restart_zubcut())
            spawn.assert_called_once_with('ZubCut.exe', '', r'C:\ZubCut')
            rel.assert_called_once()

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_restart_zubcut_skips_runas_when_admin(self):
        with patch.object(ug, 'is_admin', return_value=True):
            with patch.object(ug, '_windows_relaunch_command', return_value=('ZubCut.exe', '', r'C:\ZubCut')):
                with patch.object(ug, '_zubcut_relaunch_argv', return_value=[]):
                    with patch.object(ug, '_spawn_zubcut_same_token', return_value=True) as same:
                        with patch.object(ug, 'spawn_windows_elevated') as spawn:
                            with patch.object(ug, 'release_zubcut_single_instance'):
                                self.assertTrue(ug.restart_zubcut())
        same.assert_called_once()
        spawn.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_restart_zubcut_releases_lock_before_spawn(self):
        order: list[str] = []

        def _rel():
            order.append('release')

        def _spawn(*_a, **_k):
            order.append('spawn')
            return True

        with patch.object(ug, 'is_admin', return_value=False):
            with patch.object(ug, '_windows_relaunch_command', return_value=('ZubCut.exe', '', r'C:\ZubCut')):
                with patch.object(ug, '_zubcut_relaunch_argv', return_value=[]):
                    with patch.object(ug, 'release_zubcut_single_instance', side_effect=_rel):
                        with patch.object(ug, 'spawn_windows_elevated', side_effect=_spawn):
                            self.assertTrue(ug.restart_zubcut())
        self.assertEqual(order, ['release', 'spawn'])

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_spawn_windows_elevated_runas_verb(self):
        with patch.object(ug.ctypes.windll.shell32, 'ShellExecuteW', return_value=42) as se:
            self.assertTrue(ug.spawn_windows_elevated('ZubCut.exe', '', r'C:\ZubCut'))
            se.assert_called_once()
            self.assertEqual(se.call_args[0][1], 'runas')

    def test_relaunch_argv_includes_script_when_not_frozen(self):
        with patch.object(ug.sys, 'frozen', False, create=True), patch.object(
            ug.sys, 'argv', ['C:\\src\\zubcut.py']
        ):
            tail = ug._zubcut_relaunch_argv(handoff=True)
        self.assertEqual(tail[0], ug._ELEVATE_HANDOFF_ARG)
        self.assertTrue(tail[1].lower().endswith('zubcut.py'))

    def test_relaunch_argv_strips_existing_handoff(self):
        with patch.object(ug.sys, 'frozen', True, create=True), patch.object(
            ug.sys, 'argv', ['ZubCut.exe', ug._ELEVATE_HANDOFF_ARG]
        ):
            self.assertEqual(ug._zubcut_relaunch_argv(handoff=True), [ug._ELEVATE_HANDOFF_ARG])
            self.assertEqual(ug._zubcut_relaunch_argv(handoff=False), [])


if __name__ == '__main__':
    unittest.main()
