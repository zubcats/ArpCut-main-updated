"""Unit tests for in-app update detection."""

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, 'src'))


class UpdaterCoreTest(unittest.TestCase):
    def test_update_available_when_remote_is_newer(self):
        import tools.updater_core as uc

        remote = datetime(2026, 5, 16, 10, 11, tzinfo=timezone.utc)
        with patch.object(uc, 'APP_BUILD_TIME_ISO', '2026-05-12T07:30:00Z'), patch.object(
            uc, 'UPDATE_CHANNEL', 'main'
        ), patch.object(
            uc,
            'UPDATE_DOWNLOAD_URL_MAIN',
            'https://github.com/zubcats/ArpCut-main-updated/releases/download/stable-latest/ZubCut-Setup.exe',
        ), patch.object(uc, 'UPDATE_DOWNLOAD_URL_EXPERIMENTAL', ''), patch.object(
            uc, '_remote_installer_datetime', return_value=remote
        ):
            available, label = uc.get_update_status()
        self.assertTrue(available)
        self.assertIn('New version online', label)
        self.assertIn('May 12', label)

    def test_up_to_date_when_remote_matches_build(self):
        import tools.updater_core as uc

        t = datetime(2026, 5, 16, 10, 11, tzinfo=timezone.utc)
        with patch.object(uc, 'APP_BUILD_TIME_ISO', '2026-05-16T10:11:00Z'), patch.object(
            uc, 'UPDATE_CHANNEL', 'main'
        ), patch.object(
            uc,
            'UPDATE_DOWNLOAD_URL_MAIN',
            'https://github.com/zubcats/ArpCut-main-updated/releases/download/stable-latest/ZubCut-Setup.exe',
        ), patch.object(uc, 'UPDATE_DOWNLOAD_URL_EXPERIMENTAL', ''), patch.object(
            uc, '_remote_installer_datetime', return_value=t
        ):
            available, label = uc.get_update_status()
        self.assertFalse(available)
        self.assertIn('Up to date', label)

    def test_missing_local_build_time_offers_update(self):
        import tools.updater_core as uc

        remote = datetime(2026, 5, 16, 10, 11, tzinfo=timezone.utc)
        with patch.object(uc, 'APP_BUILD_TIME_ISO', ''), patch.object(
            uc, 'UPDATE_CHANNEL', 'main'
        ), patch.object(
            uc,
            'UPDATE_DOWNLOAD_URL_MAIN',
            'https://github.com/zubcats/ArpCut-main-updated/releases/download/stable-latest/ZubCut-Setup.exe',
        ), patch.object(uc, 'UPDATE_DOWNLOAD_URL_EXPERIMENTAL', ''), patch.object(
            uc, '_remote_installer_datetime', return_value=remote
        ):
            available, label = uc.get_update_status()
        self.assertTrue(available)
        self.assertIn('Latest online', label)


if __name__ == '__main__':
    unittest.main()
