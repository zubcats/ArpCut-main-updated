"""Import Control Panel accounts from Cloudflare KV bundles."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import license_admin as admin


class ImportKvBundleTests(unittest.TestCase):
    def test_import_merges_bundles_without_signing_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, 'paid-license-admin.json')
            key_path = os.path.join(td, 'paid-license-signing.key')
            with mock.patch.object(admin, 'PAID_LICENSE_ADMIN_DB_PATH', db_path), mock.patch.object(
                admin, 'PAID_LICENSE_ADMIN_SIGNING_KEY_PATH', key_path
            ):
                n, skipped = admin.import_license_records_from_kv_bundles(
                    [
                        {
                            'version': 1,
                            'password_salt': 'abc=',
                            'password_hash_hex': 'deadbeef',
                            'license': {
                                'payload': {
                                    'license_id': '11111111-1111-1111-1111-111111111111',
                                    'user_name': 'alice',
                                    'issued_at': '2026-01-01T00:00:00Z',
                                    'expires_at': '2027-01-01T00:00:00Z',
                                    'status': 'active',
                                },
                                'signature': 'sig',
                            },
                        }
                    ]
                )
                self.assertEqual(n, 1)
                self.assertEqual(skipped, 0)
                rows = admin.list_license_rows()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['user_name'], 'alice')
                data = json.loads(open(db_path, encoding='utf-8').read())
                self.assertEqual(
                    data['licenses'][0]['payload']['password_hash'],
                    'deadbeef',
                )
                self.assertFalse(os.path.isfile(key_path))

    def test_load_signing_key_refuses_generate_when_db_has_licenses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, 'paid-license-admin.json')
            key_path = os.path.join(td, 'paid-license-signing.key')
            with open(db_path, 'w', encoding='utf-8') as fh:
                json.dump(
                    {
                        'version': 1,
                        'licenses': [
                            {
                                'payload': {
                                    'license_id': 'x',
                                    'user_name': 'bob',
                                    'status': 'active',
                                    'expires_at': '2099-01-01T00:00:00Z',
                                },
                                'signature': 's',
                            }
                        ],
                    },
                    fh,
                )
            with mock.patch.object(admin, 'PAID_LICENSE_ADMIN_DB_PATH', db_path), mock.patch.object(
                admin, 'PAID_LICENSE_ADMIN_SIGNING_KEY_PATH', key_path
            ):
                with self.assertRaises(FileNotFoundError):
                    admin._load_signing_key()


if __name__ == '__main__':
    unittest.main()
