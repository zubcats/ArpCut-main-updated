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

    def test_up_to_date_when_commit_matches_but_asset_upload_is_later(self):
        """Installer asset upload time is later than PyInstaller stamp; same commit must not loop."""
        import tools.updater_core as uc

        commit = 'abc123def4567890'
        local_stamp = datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)
        upload_stamp = datetime(2026, 5, 16, 10, 25, tzinfo=timezone.utc)
        info = RemoteInstallerInfo(
            updated_at=upload_stamp,
            download_url=_api_asset(101),
            asset_id=101,
            size=40_000_000,
            remote_commit=commit,
            remote_built_at='2026-05-16T10:00:00Z',
        )
        with patch.object(uc, 'APP_BUILD_TIME_ISO', '2026-05-16T10:00:00Z'), patch.object(
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

    def test_up_to_date_when_commit_matches_without_local_time_stamp(self):
        import tools.updater_core as uc

        commit = 'deadbeef0001'
        info = RemoteInstallerInfo(
            updated_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
            download_url=_api_asset(102),
            asset_id=102,
            size=40_000_000,
            remote_commit=commit,
            remote_built_at='2026-05-16T12:00:00Z',
        )
        with patch.object(uc, 'APP_BUILD_TIME_ISO', ''), patch.object(
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

    def test_not_update_loop_when_local_commit_but_no_remote_build_info(self):
        import tools.updater_core as uc

        upload_stamp = datetime(2026, 5, 16, 11, 0, tzinfo=timezone.utc)
        info = RemoteInstallerInfo(
            updated_at=upload_stamp,
            download_url=_api_asset(103),
            asset_id=103,
            size=40_000_000,
            remote_commit='',
            remote_built_at='',
        )
        with patch.object(uc, 'APP_BUILD_TIME_ISO', '2026-05-16T10:00:00Z'), patch.object(
            uc, 'APP_BUILD_COMMIT', 'localonlycommit1'
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

    def test_indeterminate_when_remote_release_unreachable(self):
        """Republish races / API failures must not report False (clears green gear)."""
        import tools.updater_core as uc

        with patch.object(uc, 'APP_BUILD_TIME_ISO', '2026-05-16T10:00:00Z'), patch.object(
            uc, 'APP_BUILD_COMMIT', 'localonlycommit1'
        ), patch.object(uc, 'UPDATE_CHANNEL', 'main'), patch.object(
            uc,
            'UPDATE_DOWNLOAD_URL_MAIN',
            UPDATE_DOWNLOAD_URL_MAIN,
        ), patch.object(uc, 'UPDATE_DOWNLOAD_URL_EXPERIMENTAL', ''), patch.object(
            uc, '_cached_remote_installer_info', return_value=None
        ), patch.object(uc, '_remote_compare_datetime', return_value=None):
            available, label = uc.get_update_status()
        self.assertIsNone(available)
        self.assertEqual(label, '')

    def test_misses_are_not_cached(self):
        import tools.updater_core as uc

        uc._remote_cache = None
        with patch.object(uc, '_fetch_remote_installer_info', return_value=None) as fetch:
            self.assertIsNone(uc._cached_remote_installer_info('experimental'))
            self.assertIsNone(uc._remote_cache)
            self.assertIsNone(uc._cached_remote_installer_info('experimental'))
            self.assertEqual(fetch.call_count, 2)
        uc._remote_cache = None

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

    def test_size_mismatch_is_retryable(self) -> None:
        import tools.updater_core as uc

        err = RuntimeError(
            'Downloaded installer size mismatch (got 10485760 bytes, expected 46211455).'
        )
        self.assertTrue(uc.is_retryable_network_error(err))
        self.assertTrue(uc._is_incomplete_download_error(err))

    def test_download_retries_then_falls_back_on_truncate(self) -> None:
        """Truncated API download must retry and then try the static release URL."""
        import io
        import tools.updater_core as uc

        api = _api_asset(77)
        static = UPDATE_DOWNLOAD_URL_MAIN
        calls: list[str] = []

        class _Resp:
            def __init__(self, data: bytes, content_length: int | None = None):
                self._buf = io.BytesIO(data)
                self.headers = {}
                if content_length is not None:
                    self.headers['Content-Length'] = str(content_length)

            def read(self, n: int = -1):
                return self._buf.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        mz_pad = b'MZ' + b'\0' * 100

        def fake_urlopen(req, timeout=0, context=None):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            calls.append(url)
            if '/releases/assets/' in url:
                # Truncated body (classic ~10 MiB stall pattern, smaller for test).
                return _Resp(mz_pad + b'\0' * 200, content_length=40_000_000)
            # Static fallback succeeds with matching size.
            body = mz_pad + b'\0' * (50_000 - len(mz_pad))
            return _Resp(body, content_length=len(body))

        with patch.object(uc, '_urllib_urlopen', side_effect=fake_urlopen), patch.object(
            uc, '_DOWNLOAD_ATTEMPTS_PER_URL', 2
        ), patch.object(uc, '_authenticode_signature_info', return_value={}), patch.object(
            uc, 'time'
        ) as mock_time:
            mock_time.sleep = lambda *_a, **_k: None
            mock_time.time = lambda: 1_700_000_000
            path = uc.download_installer(
                api,
                expected_size=50_000,
                fallback_urls=[static],
            )
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.getsize(path), 50_000)
        api_tries = sum(1 for u in calls if '/releases/assets/' in u)
        self.assertGreaterEqual(api_tries, 2)
        self.assertTrue(any('cb=' in u or 'releases/download' in u for u in calls))
        try:
            os.remove(path)
        except OSError:
            pass

    def test_format_updater_error_10065_mentions_hotspot_repair(self):
        import tools.updater_core as uc

        err = OSError(None, 'host unreachable', None, 10065)
        msg = uc.format_updater_error_message(err)
        self.assertIn('Mobile hotspot', msg)
        self.assertNotIn('github', msg.lower())

    def test_urllib_ssl_context_uses_certifi_when_available(self):
        import tools.updater_core as uc

        uc._ssl_context = None
        ctx = uc._urllib_ssl_context()
        self.assertIsNotNone(ctx)
        try:
            import certifi

            self.assertTrue(os.path.isfile(certifi.where()))
        except ImportError:
            pass

    def test_github_repo_slug_matches_constants(self):
        self.assertEqual(GITHUB_REPO_SLUG, 'zubcats/ArpCut-main-updated')


if __name__ == '__main__':
    unittest.main()
