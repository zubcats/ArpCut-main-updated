"""Unit tests for in-app update detection."""

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, 'src'))

from constants import GITHUB_REPO_SLUG, UPDATE_DOWNLOAD_URL_MAIN
from tools.updater_core import (
    RemoteInstallerInfo,
    _download_request_url,
    _is_github_release_asset_api_url,
    format_updater_error_message,
    get_update_status,
    installer_download_candidates,
    resolve_installer_download_url,
)


def _api_asset(asset_id: int) -> str:
    return f'https://api.github.com/repos/{GITHUB_REPO_SLUG}/releases/assets/{asset_id}'


class UpdaterCoreTest(unittest.TestCase):
    def test_update_available_when_remote_is_newer(self):
        import tools.updater_core as uc

        remote = datetime(2026, 5, 16, 10, 11, tzinfo=timezone.utc)
        info = RemoteInstallerInfo(
            updated_at=remote,
            download_url=_api_asset(99),
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
            UPDATE_DOWNLOAD_URL_MAIN,
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
            download_url=_api_asset(100),
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
            UPDATE_DOWNLOAD_URL_MAIN,
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
            download_url=_api_asset(42),
            asset_id=42,
            size=1,
            remote_commit='',
            remote_built_at='',
        )
        with patch.object(uc, '_cached_remote_installer_info', return_value=info):
            url = uc.resolve_installer_download_url()
        self.assertIn('/releases/assets/42', url)

    def test_installer_download_candidates_includes_static_fallback(self):
        import tools.updater_core as uc

        info = RemoteInstallerInfo(
            updated_at=None,
            download_url=_api_asset(7),
            asset_id=7,
            size=1,
            remote_commit='',
            remote_built_at='',
        )
        static = UPDATE_DOWNLOAD_URL_MAIN
        with patch.object(uc, '_cached_remote_installer_info', return_value=info), patch.object(
            uc, 'UPDATE_CHANNEL', 'main'
        ), patch.object(uc, 'UPDATE_DOWNLOAD_URL_MAIN', static), patch.object(
            uc, 'UPDATE_DOWNLOAD_URL_EXPERIMENTAL', ''
        ):
            urls = uc.installer_download_candidates()
        self.assertEqual(len(urls), 2)
        self.assertIn('/releases/assets/7', urls[0])
        self.assertEqual(urls[1], static)

    def test_asset_api_url_not_cache_busted(self) -> None:
        api = _api_asset(42)
        self.assertTrue(_is_github_release_asset_api_url(api))
        self.assertEqual(_download_request_url(api), api)
        static = UPDATE_DOWNLOAD_URL_MAIN
        bust = _download_request_url(static)
        self.assertIn('cb=', bust)
        self.assertNotEqual(bust, static)

    def test_format_updater_error_404_suggests_retry(self) -> None:
        import urllib.error

        err = urllib.error.HTTPError(
            _api_asset(1),
            404,
            'Not Found',
            None,
            None,
        )
        msg = format_updater_error_message(err)
        self.assertIn('stale', msg.lower())
        self.assertIn('again', msg.lower())

    def test_format_updater_error_10065_mentions_hotspot_repair(self):
        import tools.updater_core as uc

        err = OSError(None, 'host unreachable', None, 10065)
        msg = uc.format_updater_error_message(err)
        self.assertIn('Mobile hotspot', msg)
        self.assertIn('github.com', msg)


if __name__ == '__main__':
    unittest.main()
