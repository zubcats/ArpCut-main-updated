"""Diagnostic ZC codes linked into crash reporting."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestZcCodeCache(unittest.TestCase):
    def setUp(self) -> None:
        from tools import user_errors as ue

        with ue._zc_lock:
            ue._zc_seen.clear()

    def test_note_and_latest_worst_first(self):
        from tools.user_errors import latest_zc_codes, note_zc_code

        note_zc_code('ZC-WPA3', level='warn', source='pc_readiness')
        note_zc_code('ZC-NPCAP', level='fail', source='pc_readiness')
        note_zc_code('ZC-WPA3', level='ok', source='later')  # keep worse
        rows = latest_zc_codes()
        self.assertEqual([r['code'] for r in rows], ['ZC-NPCAP', 'ZC-WPA3'])
        self.assertEqual(rows[0]['level'], 'fail')
        self.assertEqual(rows[1]['level'], 'warn')

    def test_rejects_crash_ref_shaped(self):
        from tools.user_errors import latest_zc_codes, note_zc_code

        note_zc_code('ZC-ABC123', level='fail')
        self.assertEqual(latest_zc_codes(), [])

    def test_format_error_code_notes_registry(self):
        from tools.user_errors import format_error_code, latest_zc_codes

        text = format_error_code('ZC-FW', 'rule write failed')
        self.assertIn('ZC-FW', text)
        codes = [r['code'] for r in latest_zc_codes()]
        self.assertIn('ZC-FW', codes)

    def test_header_roundtrip(self):
        from tools.user_errors import (
            format_zc_codes_header,
            note_zc_code,
            parse_zc_codes_header,
        )

        note_zc_code('ZC-MLO', level='warn', source='pc_readiness')
        header = format_zc_codes_header()
        self.assertIn('ZC-MLO:warn', header)
        log = f'reference=ZC-TEST01\nzc_codes={header}\n\nTraceback\n'
        parsed = parse_zc_codes_header(log)
        self.assertEqual(parsed[0]['code'], 'ZC-MLO')
        self.assertEqual(parsed[0]['level'], 'warn')

    def test_catalog_covers_registry(self):
        from tools.user_errors import ERROR_CODES, zc_code_catalog

        cat = zc_code_catalog()
        self.assertEqual(len(cat), len(ERROR_CODES))
        self.assertTrue(all(c['code'] in ERROR_CODES for c in cat))


class TestCrashPayloadZcCodes(unittest.TestCase):
    def setUp(self) -> None:
        from tools import user_errors as ue

        with ue._zc_lock:
            ue._zc_seen.clear()

    def test_build_payload_includes_observed_and_catalog(self):
        from tools.crash_remote_report import _build_payload
        from tools.user_errors import ERROR_CODES, note_zc_code

        note_zc_code('ZC-ADMIN', level='fail', source='pc_readiness')
        payload = _build_payload('ZC-ABC123', 'ValueError: boom\n')
        codes = [c['code'] for c in payload.get('zc_codes') or []]
        self.assertIn('ZC-ADMIN', codes)
        catalog_codes = {c['code'] for c in payload.get('zc_catalog') or []}
        self.assertEqual(catalog_codes, set(ERROR_CODES))

    def test_build_payload_parses_log_header_when_cache_empty(self):
        from tools.crash_remote_report import _build_payload

        log = (
            'reference=ZC-ABC123\n'
            'zc_codes=ZC-ICS:fail,ZC-WD:warn\n'
            '\n'
            'RuntimeError: hot path\n'
        )
        payload = _build_payload('ZC-ABC123', log)
        codes = {c['code']: c['level'] for c in payload.get('zc_codes') or []}
        self.assertEqual(codes.get('ZC-ICS'), 'fail')
        self.assertEqual(codes.get('ZC-WD'), 'warn')


if __name__ == '__main__':
    unittest.main()
