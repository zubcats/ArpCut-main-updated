"""Unit tests for in-app update detection."""

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, 'src'))

from tools.updater_core import RemoteInstallerInfo, get_update_status, resolve_installer_download_url


class UpdaterCoreTest(unittest.TestCase):
    def test_update_available_when_remote_is_newer(self):
        import tools.updater_core as uc

        remote = datetime(2026, 5, 16, 10, 11, tzinfo=timezone.utc)
        info = RemoteInstallerInfo(
            updated_at=remote,
            download_url='https://api.github.com/repos/zubcats/ArpCut-main-updated/releases/assets/99',
            asset_id=99,
            size=40_000_000,
            remote_commit='abc123def456',
            remote_built_at='2026-05-16T10:11:00Z',
        )
        with patch.object(uc, 'APP_BUILD_TIME_ISO', '2026-05-12T07:30:00Z'), patch.object(
            uc, 'APP_BUILD_COMMIT', 'oldcommit0000'
        ), patch.object(uc, 'UPDATE_CHANNEL', 'main'), patch.object(
            uc,
            'UPDATE_DOWNLOAD_URL_MAIN',
            'https://github.com/zubcats/ArpCut-main-updated/releases/download/stable-latest/ZubCut-Setup.exe',
        ), patch.object(uc, 'UPDATE_DOWNLOAD_URL_EXPERIMENTAL', ''), patch.object(
            uc, '_cached_remote_installer_info', return_value=info
        ):
            available, label = uc.get_update_status()
        self.assertTrue(available)
        self.assertIn('New', label)

    def test_up_to_date_when_remote_matches_build(self):
        import tools.updater_core as uc

        t = datetime(2026, 5, 16, 10, 11, tzinfo=timezone.utc)
        commit = 'samecommit1234'
        info = RemoteInstallerInfo(
            updated_at=t,
            download_url='https://api.github.com/repos/zubcats/ArpCut-main-updated/releases/assets/100',
            asset_id=100,
            size=40_000_000,
            remote_commit=commit,
            remote_built_at='2026-05-16T10:11:00Z',
        )
        with patch.object(uc, 'APP_BUILD_TIME_ISO', '2026-05-16T10:11:00Z'), patch.object(
            uc, 'APP_BUILD_COMMIT', commit
        ), patch.object(uc, 'UPDATE_CHANNEL', 'main'), patch.object(
            uc,
            'UPDATE_DOWNLOAD_URL_MAIN',
            'https://github.com/zubcats/ArpCut-main-updated/releases/download/stable-latest/ZubCut-Setup.exe',
        ), patch.object(uc, 'UPDATE_DOWNLOAD_URL_EXPERIMENTAL', ''), patch.object(
            uc, '_cached_remote_installer_info', return_value=info
        ):
            available, label = uc.get_update_status()
        self.assertFalse(available)
        self.assertIn('Up to date', label)

    def test_resolve_download_uses_api_asset_url(self):
        import tools.updater_core as uc

        info = RemoteInstallerInfo(
            updated_at=None,
            download_url='https://api.github.com/repos/zubcats/ArpCut-main-updated/releases/assets/42',
            asset_id=42,
            size=1,
            remote_commit='',
            remote_built_at='',
        )
        with patch.object(uc, '_cached_remote_installer_info', return_value=info):
            url = uc.resolve_installer_download_url()
        self.assertIn('/releases/assets/42', url)


if __name__ == '__main__':
    unittest.main()
