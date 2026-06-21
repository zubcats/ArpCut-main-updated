"""Install Latest Build must not block the GUI on GitHub API before confirm."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestUpdaterInstallDialog(unittest.TestCase):
    @staticmethod
    def _settings_py() -> str:
        path = os.path.join(_SRC, 'gui', 'settings.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_check_update_uses_cache_before_confirm(self) -> None:
        src = self._settings_py()
        block = src[src.index('def checkUpdate'): src.index('def _channel_label', src.index('def checkUpdate'))]
        self.assertIn('installer_download_candidates(force_refresh=False)', block)
        self.assertNotIn('installer_download_candidates(force_refresh=True)', block)
        self.assertIn('refresh_metadata_first=True', block)

    def test_refresh_plan_helper_exists(self) -> None:
        from tools.updater_core import refresh_installer_download_plan

        self.assertTrue(callable(refresh_installer_download_plan))


if __name__ == '__main__':
    unittest.main()
