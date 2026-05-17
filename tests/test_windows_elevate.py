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
            with patch.object(ug.ctypes.windll.shell32, 'ShellExecuteW', return_value=5):
                with patch.object(ug.ctypes.windll.user32, 'MessageBoxW'):
                    self.assertFalse(ug.ensure_windows_elevated())


if __name__ == '__main__':
    unittest.main()
