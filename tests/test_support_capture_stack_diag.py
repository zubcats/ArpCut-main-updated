"""Capture stack diagnostic (Logs → Capture stack)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tools import support_capture_stack_diag as csd  # noqa: E402


class TestCaptureStackReport(unittest.TestCase):
    def test_format_skipped_not_admin(self) -> None:
        text = csd.format_capture_stack_report(
            {
                'admin': False,
                'skipped': True,
                'note': 'Run ZubCut as Administrator for Npcap capture tests.',
                'saved_iface': 'Wi-Fi',
                'sniffer_ok': False,
                'l2_ok': False,
                'tokens_tried': [],
            }
        )
        self.assertIn('SCREENSHOT THIS SUMMARY', text)
        self.assertIn('[FAIL] Running as Administrator', text)
        self.assertIn('Capture probe skipped', text)
        self.assertNotIn('192.168.', text)

    def test_format_pass(self) -> None:
        text = csd.format_capture_stack_report(
            {
                'admin': True,
                'skipped': False,
                'saved_iface': 'Wi-Fi',
                'iface_label': 'Wi-Fi',
                'sniffer_ok': True,
                'l2_ok': True,
                'sniff_iface': 'GUID',
                'l2_iface': 'GUID',
                'tokens_tried': ['GUID', 'Wi-Fi'],
            }
        )
        self.assertIn('[PASS] Npcap sniffer', text)
        self.assertIn('[PASS] Npcap L2 send socket', text)

    def test_run_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            diag = Path(tmp) / 'ZubCut Diagnostics'
            diag.mkdir()
            probe = {
                'admin': True,
                'skipped': False,
                'saved_iface': 'Wi-Fi',
                'iface_label': 'Wi-Fi',
                'sniffer_ok': True,
                'l2_ok': False,
                'sniff_iface': 'tok',
                'tokens_tried': ['tok'],
                'l2_errors': ['boom'],
            }
            with (
                mock.patch.object(sys, 'platform', 'win32'),
                mock.patch(
                    'tools.diag_paths.ensure_zubcut_diagnostics_dir', return_value=diag
                ),
                mock.patch.object(csd, 'probe_capture_stack', return_value=probe),
                mock.patch.object(csd, '_open_report') as open_r,
            ):
                ok, msg, path = csd.run_capture_stack_diag(open_report=True)
            self.assertFalse(ok)
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.is_file())
            body = path.read_text(encoding='utf-8')
            self.assertIn('[FAIL] Npcap L2 send socket', body)
            self.assertIn('Capture stack', msg)
            self.assertIn(str(path), msg)
            open_r.assert_called_once()

    def test_non_windows(self) -> None:
        with mock.patch.object(sys, 'platform', 'linux'):
            ok, msg, path = csd.run_capture_stack_diag()
        self.assertFalse(ok)
        self.assertIsNone(path)
        self.assertIn('Windows-only', msg)


class TestLogsCaptureButton(unittest.TestCase):
    def test_logs_window_has_capture_stack_button(self) -> None:
        path = os.path.join(_SRC, 'gui', 'logs_window.py')
        src = Path(path).read_text(encoding='utf-8')
        self.assertIn("setObjectName('logsDiagCaptureBtn')", src)
        self.assertIn('Capture stack', src)
        self.assertIn('def _run_capture_stack_check', src)
        self.assertIn('launch_capture_stack_diag', src)

    def test_diag_buttons_share_charcoal_theme(self) -> None:
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        src = Path(path).read_text(encoding='utf-8')
        self.assertIn('QPushButton#logsDiagCaptureBtn', src)
        self.assertIn('QPushButton#logsDiagLanBtn', src)
        self.assertIn('QPushButton#logsDiagHotspotBtn', src)
        start = src.index('QFrame#logsDiagPanel')
        end = src.index('QPushButton#logsDiagHotspotBtn:pressed')
        block = src[start:end]
        self.assertNotIn('#19232D', block)
        self.assertNotIn('#1A72BB', block)


if __name__ == '__main__':
    unittest.main()
