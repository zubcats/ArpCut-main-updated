"""ZubCut Control Panel unit tests (no GUI)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestControlPanelConstants(unittest.TestCase):
    def test_display_name_and_update_url(self) -> None:
        from constants import (
            CONTROL_PANEL_BUNDLE_NAME,
            CONTROL_PANEL_DISPLAY_NAME,
            CONTROL_PANEL_UPDATE_URL,
            PAID_LICENSE_MANAGER_UPDATE_URL,
        )

        self.assertEqual(CONTROL_PANEL_DISPLAY_NAME, 'ZubCut Control Panel')
        self.assertEqual(CONTROL_PANEL_BUNDLE_NAME, 'ZubCutControlPanel')
        self.assertIn('control-panel-latest', CONTROL_PANEL_UPDATE_URL)
        self.assertIn('ZubCut-Control-Panel-Setup.exe', CONTROL_PANEL_UPDATE_URL)
        self.assertIn('paid-license-manager-latest', PAID_LICENSE_MANAGER_UPDATE_URL)
        self.assertIn('ZubCut-License-Manager-Setup.exe', PAID_LICENSE_MANAGER_UPDATE_URL)


class TestControlPanelSource(unittest.TestCase):
    def test_entry_and_window_exist(self) -> None:
        entry = os.path.join(_ROOT, 'src', 'zubcut_control_panel.py')
        window = os.path.join(_ROOT, 'src', 'gui', 'control_panel.py')
        crashes = os.path.join(_ROOT, 'src', 'gui', 'crash_reports_panel.py')
        self.assertTrue(os.path.isfile(entry))
        self.assertTrue(os.path.isfile(window))
        self.assertTrue(os.path.isfile(crashes))
        with open(window, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('class ControlPanelWindow', src)
        self.assertIn('Crash reports', src)
        self.assertIn('Install latest build', src)
        self.assertNotIn('utils_gui', src)
        self.assertNotIn('tools.utils', src)
        self.assertNotIn('register_window_surface_effects(self)', src)
        self.assertNotIn('setup_frameless_main_window', src)
        self.assertNotIn('FramelessResizableMixin', src)
        self.assertNotIn('QInputDialog.getText', src)
        self.assertNotIn('QInputDialog.getInt', src)
        self.assertNotIn('QInputDialog.getItem', src)
        self.assertIn('def _ask_line_text', src)
        self.assertIn("_show_panel_error(self, 'Create Account'", src)
        self.assertIn('except Exception as exc:', src)
        self.assertIn('QComboBox', src)
        self.assertIn('QSpinBox', src)

    def test_entry_slot_errors_do_not_force_exit(self) -> None:
        entry = os.path.join(_ROOT, 'src', 'zubcut_control_panel.py')
        with open(entry, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('excepthook', src)
        self.assertIn('_install_control_panel_excepthook', src)
        self.assertNotIn('os._exit(', src)
        self.assertNotIn('crash_feedback', src)

    def test_crash_api_module(self) -> None:
        from tools.control_panel_crashes import list_crash_reports

        self.assertTrue(callable(list_crash_reports))

    def test_crash_panel_source_avoids_expanding_status_banner(self) -> None:
        path = os.path.join(_ROOT, 'src', 'gui', 'crash_reports_panel.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('QSizePolicy.Ignored', src)
        self.assertIn("Refresh failed. See details in the popup.", src)
        self.assertIn('self.lblStatus.setToolTip', src)
        self.assertIn('ZC codes', src)
        self.assertIn('ZC code legend', src)
        self.assertIn('zc_codes', src)
        self.assertNotIn('#19232D', src)
        self.assertNotIn('#1A72BB', src)


class TestWorkerHttpHeaders(unittest.TestCase):
    def test_format_worker_api_error_invalid_credentials(self) -> None:
        from tools.license_cloud_sync import format_worker_api_error

        msg = format_worker_api_error(401, 'Invalid credentials.')
        self.assertIn('crash admin API', msg)
        self.assertIn('wrangler deploy', msg)

    def test_format_worker_api_error_unauthorized(self) -> None:
        from tools.license_cloud_sync import format_worker_api_error

        msg = format_worker_api_error(401, 'Unauthorized.')
        self.assertIn('ADMIN_SECRET', msg)

    def test_worker_http_headers_include_custom_user_agent(self) -> None:
        from tools.license_cloud_sync import WORKER_HTTP_USER_AGENT, worker_http_headers

        headers = worker_http_headers()
        self.assertEqual(headers['User-Agent'], WORKER_HTTP_USER_AGENT)
        self.assertEqual(headers['User-Agent'], 'ZubCut-ControlPanel/1.0')
        self.assertEqual(headers['Content-Type'], 'application/json')

    @patch('tools.control_panel_crashes.urllib.request.urlopen')
    @patch('tools.control_panel_crashes.load_cloud_sync_settings')
    def test_list_crash_reports_sends_user_agent(self, mock_settings, mock_urlopen) -> None:
        from tools.control_panel_crashes import list_crash_reports
        from tools.license_cloud_sync import WORKER_HTTP_USER_AGENT

        mock_settings.return_value = {
            'worker_base_url': 'https://example.test',
            'admin_secret': 'sekret',
        }
        resp = MagicMock()
        resp.read.return_value = b'{"ok": true, "crashes": []}'
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        rows = list_crash_reports(limit=5)
        self.assertEqual(rows, [])
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_header('User-agent'), WORKER_HTTP_USER_AGENT)


if __name__ == '__main__':
    unittest.main()
