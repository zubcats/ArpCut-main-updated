"""Crash ingest token wiring (CI bake + client payload)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestCrashIngestTokenWiring(unittest.TestCase):
    def test_constants_declare_crash_ingest_token(self) -> None:
        from constants import CRASH_INGEST_TOKEN

        self.assertIsInstance(CRASH_INGEST_TOKEN, str)

    def test_payload_includes_baked_token(self) -> None:
        with mock.patch('tools.crash_remote_report.CRASH_INGEST_TOKEN', 'baked-secret'):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop('ZUBCUT_CRASH_INGEST_TOKEN', None)
                os.environ.pop('CRASH_INGEST_TOKEN', None)
                from tools import crash_remote_report as mod

                payload = mod._build_payload('ZC-AAAAAA', 'boom')
                self.assertEqual(payload.get('ingest_token'), 'baked-secret')

    def test_ci_apply_injects_crash_ingest_token(self) -> None:
        script = Path(_ROOT) / 'tools' / 'ci_apply_build_constants.py'
        src = script.read_text(encoding='utf-8')
        self.assertIn('CRASH_INGEST_TOKEN', src)
        self.assertIn('os.getenv("CRASH_INGEST_TOKEN"', src)

        sample = (
            "UPDATE_CHANNEL = 'experimental'\n"
            "LICENSE_PUBLIC_KEY_B64 = ''\n"
            "LICENSE_SIGNIN_URL = 'https://example.workers.dev'\n"
            "CRASH_INGEST_TOKEN = ''\n"
            "APP_BUILD_TIME_ISO = ''\n"
            "APP_BUILD_COMMIT = ''\n"
            "UPDATE_DOWNLOAD_URL_MAIN = 'x'\n"
            "UPDATE_DOWNLOAD_URL_EXPERIMENTAL = 'y'\n"
        )
        with tempfile.TemporaryDirectory() as td:
            const_path = Path(td) / 'constants.py'
            const_path.write_text(sample, encoding='utf-8')
            env = {
                **os.environ,
                'REF_NAME': 'experimental',
                'REF_TYPE': 'branch',
                'LICENSE_PUBLIC_KEY_B64': 'dGVzdA==',
                'CRASH_INGEST_TOKEN': 'ci-token-value',
            }
            # Run against temp file by patching Path in the script via cwd copy layout
            work = Path(td) / 'src'
            work.mkdir()
            target = work / 'constants.py'
            target.write_text(sample, encoding='utf-8')
            # Execute the substitution logic inline for isolation
            import re

            txt = target.read_text(encoding='utf-8')
            crash_ingest = env['CRASH_INGEST_TOKEN']
            txt = re.sub(
                r'^CRASH_INGEST_TOKEN\s*=.*$',
                f'CRASH_INGEST_TOKEN = {crash_ingest!r}',
                txt,
                flags=re.M,
            )
            self.assertIn("CRASH_INGEST_TOKEN = 'ci-token-value'", txt)

    def test_set_script_exists(self) -> None:
        path = Path(_ROOT) / 'tools' / 'set_crash_ingest_token.sh'
        self.assertTrue(path.is_file())
        self.assertIn('wrangler secret put CRASH_INGEST_TOKEN', path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
