"""ZubCut Control Panel unit tests (no GUI)."""
from __future__ import annotations

import os
import sys
import unittest

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

    def test_crash_api_module(self) -> None:
        from tools.control_panel_crashes import list_crash_reports

        self.assertTrue(callable(list_crash_reports))


if __name__ == '__main__':
    unittest.main()
