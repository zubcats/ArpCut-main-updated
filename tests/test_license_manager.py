"""License Manager unit tests (no GUI)."""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_LM = os.path.join(_ROOT, 'license-manager')
if _LM not in sys.path:
    sys.path.insert(0, _LM)

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from license_manager.admin_crypto import (
    build_account_license,
    pbkdf2_sha256_hex,
    public_key_b64,
    renew_account_license,
)


class TestLicenseManagerCrypto(unittest.TestCase):
    def test_pbkdf2_matches_worker_style(self) -> None:
        salt_b64 = base64.b64encode(b'test-salt-bytes').decode('ascii')
        hex1 = pbkdf2_sha256_hex('secret', salt_b64)
        hex2 = pbkdf2_sha256_hex('secret', salt_b64)
        self.assertEqual(hex1, hex2)
        self.assertEqual(len(hex1), 64)

    def test_build_and_renew_preserve_password(self) -> None:
        sk = Ed25519PrivateKey.generate()
        bundle, local = build_account_license(
            account_key='demo',
            password='customer-pass',
            private_key=sk,
            days=7,
        )
        self.assertIn('password_hash_hex', bundle)
        self.assertIn('license', bundle)
        self.assertEqual(local['account_key'], 'demo')
        pub = public_key_b64(sk)
        self.assertTrue(len(pub) > 20)
        bundle2, local2 = renew_account_license(local, private_key=sk, days=14, password=None)
        self.assertEqual(local2['password_hash_hex'], local['password_hash_hex'])
        self.assertNotEqual(local2['expires_at'], local['expires_at'])
        self.assertIn('license', bundle2)


class TestCrashReportsWidgetSource(unittest.TestCase):
    def test_widget_file_exists(self) -> None:
        path = os.path.join(_LM, 'license_manager', 'ui', 'crash_reports_widget.py')
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('class CrashReportsWidget', src)
        self.assertIn('list_crashes', src)
        self.assertIn('set_account_filter', src)
        self.assertIn('cmbAccount', src)


if __name__ == '__main__':
    unittest.main()
