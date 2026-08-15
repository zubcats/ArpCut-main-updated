"""Ed25519 license verify (cryptography backend, compatible with PyNaCl-signed licenses)."""

from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools import license_offline as lic


def _sign_payload(payload: dict, private_key: Ed25519PrivateKey) -> dict:
    msg = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    sig = private_key.sign(msg)
    pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64'] = base64.b64encode(pub).decode('ascii')
    return {
        'payload': payload,
        'signature': base64.b64encode(sig).decode('ascii'),
    }


class LicenseOfflineCryptoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_key = os.environ.get('ZUBCUT_LICENSE_PUBLIC_KEY_B64')
        self._old_prev = os.environ.get('ZUBCUT_LICENSE_PUBLIC_KEY_B64_PREV')

    def tearDown(self) -> None:
        if self._old_key is None:
            os.environ.pop('ZUBCUT_LICENSE_PUBLIC_KEY_B64', None)
        else:
            os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64'] = self._old_key
        if self._old_prev is None:
            os.environ.pop('ZUBCUT_LICENSE_PUBLIC_KEY_B64_PREV', None)
        else:
            os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64_PREV'] = self._old_prev

    def test_validate_signed_license(self) -> None:
        sk = Ed25519PrivateKey.generate()
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        payload = {
            'status': 'active',
            'expires_at': expires,
            'account': 'test-user',
        }
        doc = _sign_payload(payload, sk)
        result = lic.validate_license_document(doc)
        self.assertTrue(result.ok, result.reason)

    def test_rejects_tampered_signature(self) -> None:
        sk = Ed25519PrivateKey.generate()
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        payload = {'status': 'active', 'expires_at': expires}
        doc = _sign_payload(payload, sk)
        doc['signature'] = base64.b64encode(b'\x00' * 64).decode('ascii')
        result = lic.validate_license_document(doc)
        self.assertFalse(result.ok)
        self.assertIn('signature', result.reason.lower())

    def test_validate_accepts_previous_verify_key(self) -> None:
        old_sk = Ed25519PrivateKey.generate()
        new_sk = Ed25519PrivateKey.generate()
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        payload = {'status': 'active', 'expires_at': expires, 'account': 'legacy'}
        msg = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
        old_pub = old_sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        new_pub = new_sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64'] = base64.b64encode(new_pub).decode('ascii')
        os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64_PREV'] = base64.b64encode(old_pub).decode('ascii')
        doc = {
            'payload': payload,
            'signature': base64.b64encode(old_sk.sign(msg)).decode('ascii'),
        }
        result = lic.validate_license_document(doc)
        self.assertTrue(result.ok, result.reason)

    def test_license_crypto_self_test(self) -> None:
        ok, report = lic.license_crypto_self_test()
        self.assertTrue(ok, report)


if __name__ == '__main__':
    unittest.main()
