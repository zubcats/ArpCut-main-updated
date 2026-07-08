"""Crash remote reporting client and dialog hooks."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestCrashRemoteReport(unittest.TestCase):
    def test_build_payload_uses_body_and_parses_exception(self) -> None:
        from tools.crash_remote_report import _build_payload

        log = 'Traceback (most recent call last):\n  File "x.py", line 1\nValueError: bad mac\n'
        payload = _build_payload('ZC-ABC123', log, exc_type='', exc_message='')
        self.assertEqual(payload['ref'], 'ZC-ABC123')
        self.assertEqual(payload['body'], log)
        self.assertEqual(payload['exc_type'], 'ValueError')
        self.assertEqual(payload['exc_message'], 'bad mac')

    def test_pending_crash_roundtrip(self) -> None:
        from tools import crash_remote_report as mod

        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, 'ZubCut-crash-ZC-TEST01.log')
            with open(log_path, 'w', encoding='utf-8') as fh:
                fh.write('test log\n')
            pending = os.path.join(td, 'pending.json')
            with patch.object(mod, 'pending_crash_path', return_value=pending):
                mod.save_pending_crash('ZC-TEST01', log_path)
                loaded = mod.load_pending_crash()
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded['ref'], 'ZC-TEST01')
                self.assertEqual(loaded['logPath'], log_path)
                mod.clear_pending_crash()
                self.assertIsNone(mod.load_pending_crash())

    def test_build_payload_includes_license_id(self) -> None:
        from tools import crash_remote_report as mod

        with patch.object(mod, '_license_identity', return_value=('demo-user', 'lic-uuid-123')):
            payload = mod._build_payload('ZC-ABC123', 'ValueError: x\n')
        self.assertEqual(payload['account_hint'], 'demo-user')
        self.assertEqual(payload['license_id'], 'lic-uuid-123')

    @patch('tools.crash_remote_report._post_json')
    def test_submit_posts_to_crash_endpoint(self, mock_post) -> None:
        from tools.crash_remote_report import submit_crash_report

        mock_post.return_value = (True, 'ok', {'ok': True, 'ref': 'ZC-ABC123'})
        with patch('tools.crash_remote_report._crash_report_url', return_value='https://example.test'):
            ok, msg = submit_crash_report('ZC-ABC123', 'body text')
        self.assertTrue(ok)
        args = mock_post.call_args[0]
        self.assertEqual(args[0], 'https://example.test/crash')
        self.assertEqual(args[1]['ref'], 'ZC-ABC123')
        self.assertEqual(args[1]['body'], 'body text')


class TestCrashFeedbackHooks(unittest.TestCase):
    @staticmethod
    def _crash_feedback_src() -> str:
        path = os.path.join(_SRC, 'tools', 'crash_feedback.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_dialog_has_send_report_button(self) -> None:
        src = self._crash_feedback_src()
        self.assertIn("addButton('Send report'", src)
        self.assertIn('_attempt_remote_send', src)

    def test_startup_schedules_pending_upload(self) -> None:
        src = self._crash_feedback_src()
        self.assertIn('schedule_pending_crash_upload', src)
        zubcut = os.path.join(_SRC, 'zubcut.py')
        with open(zubcut, encoding='utf-8') as fh:
            main_src = fh.read()
        self.assertIn('schedule_pending_crash_upload()', main_src)


if __name__ == '__main__':
    unittest.main()
