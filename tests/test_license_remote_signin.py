from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import base64
import hashlib
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.license_offline import resolve_license_account, validate_license_document
from tools.license_remote_signin import (
    fetch_license_document_via_signin,
    license_transient_reason,
    normalize_signin_base_url,
    signin_failure_hint,
)


class TestLicenseRemoteSignin(unittest.TestCase):
    def test_license_transient_reason_dns(self) -> None:
        raw = (
            'Could not reach license server (HTTPSConnectionPool(host='
            "'zubcut-license-signin.zubcats.workers.dev', port=443): "
            'Max retries exceeded with url: /validate (Caused by NameResolutionError('
            '"HTTPSConnection(host=\'zubcut-license-signin.zubcats.workers.dev\', port=443): '
            "Failed to resolve 'zubcut-license-signin.zubcats.workers.dev' "
            '([Errno 11001] getaddrinfo failed)"))).'
        )
        self.assertEqual(
            license_transient_reason(raw),
            'Offline — cannot resolve license server (check internet/DNS). Will retry.',
        )

    def test_license_transient_reason_timeout(self) -> None:
        self.assertEqual(
            license_transient_reason('Connection timed out after 12s'),
            'License server timed out. Will retry.',
        )

    def test_fetch_signin_lowercases_account(self) -> None:
        from tools import license_remote_signin as lrs

        captured: dict = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {'ok': False, 'error': 'Invalid credentials.'}

        def _fake_post(url, json=None, **kwargs):
            captured['json'] = dict(json or {})
            return _Resp()

        orig_post = lrs.requests.post
        try:
            lrs.requests.post = _fake_post
            data, _err = fetch_license_document_via_signin(
                'https://example.test/signin', 'MyAccount', 'secret'
            )
        finally:
            lrs.requests.post = orig_post
        self.assertIsNone(data)
        self.assertEqual(captured['json']['account'], 'myaccount')

    def test_remote_signin_does_not_require_payload_password_hash_match(self) -> None:
        """After server auth, signature/expiry check must not re-verify payload password_hash."""
        sk = Ed25519PrivateKey.generate()
        pub = sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64'] = base64.b64encode(pub).decode('ascii')
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        salt = base64.b64encode(b'server-kv-salt').decode('ascii')
        payload = {
            'status': 'active',
            'expires_at': expires,
            'user_name': 'demo',
            'password_salt': salt,
            'password_hash': hashlib.pbkdf2_hmac(
                'sha256', b'wrong-local-check', base64.b64decode(salt), 100_000
            ).hex(),
        }
        msg = __import__('json').dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
        doc = {
            'payload': payload,
            'signature': base64.b64encode(sk.sign(msg)).decode('ascii'),
        }
        with_password = validate_license_document(doc, sign_in_password='correct-server-password')
        self.assertFalse(with_password.ok)
        self.assertEqual(with_password.reason, 'Wrong password')
        without_password = validate_license_document(doc)
        self.assertTrue(without_password.ok, without_password.reason)

    def test_resolve_license_account_prefers_signin_account(self) -> None:
        data = {
            'signin_account': 'KvKey',
            'payload': {'user_name': 'other', 'account': 'legacy'},
        }
        self.assertEqual(resolve_license_account(data), 'kvkey')

    def test_resolve_license_account_falls_back_to_payload_fields(self) -> None:
        self.assertEqual(
            resolve_license_account({'payload': {'account': 'LegacyUser'}}),
            'legacyuser',
        )
        self.assertEqual(
            resolve_license_account({'payload': {'user_name': 'Display'}}),
            'display',
        )

    def test_validate_session_allows_missing_license_id(self) -> None:
        from tools import license_remote_signin as lrs

        captured: dict = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {'ok': True}

        def _fake_post(url, json=None, **kwargs):
            captured['json'] = dict(json or {})
            return _Resp()

        orig_post = lrs.requests.post
        try:
            lrs.requests.post = _fake_post
            ok, reason = lrs.validate_active_license_session(
                'https://example.test/signin', 'myaccount', ''
            )
        finally:
            lrs.requests.post = orig_post
        self.assertTrue(ok)
        self.assertEqual(captured['json']['account'], 'myaccount')
        self.assertEqual(captured['json']['license_id'], '')

    def test_normalize_signin_base_url_strips_validate_suffix(self) -> None:
        self.assertEqual(
            normalize_signin_base_url('https://example.test/validate'),
            'https://example.test',
        )
        self.assertEqual(
            normalize_signin_base_url('https://example.test/signin/validate'),
            'https://example.test/signin',
        )

    def test_signin_failure_hint_signature(self) -> None:
        hint = signin_failure_hint('License signature invalid.')
        self.assertIn('LICENSE_PUBLIC_KEY_B64', hint)

    def test_signin_failure_hint_invalid_credentials(self) -> None:
        hint = signin_failure_hint('Invalid credentials.')
        self.assertIn('Push selected to cloud', hint)

    def test_ensure_signin_verify_key_local_only(self) -> None:
        from tools import license_remote_signin as lrs

        os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64'] = 'YWJjZGVm'
        try:
            ok, err = lrs.ensure_signin_verify_key()
            self.assertTrue(ok, err)
        finally:
            os.environ.pop('ZUBCUT_LICENSE_PUBLIC_KEY_B64', None)

    def test_effective_key_prefers_constants_over_disk(self) -> None:
        from tools import license_offline as lo
        import tempfile

        old = lo.LICENSE_PUBLIC_KEY_B64
        old_prev = getattr(lo, 'LICENSE_PUBLIC_KEY_B64_PREV', '')
        old_path = lo.LICENSE_FILE_PATH
        old_env = os.environ.pop('ZUBCUT_LICENSE_PUBLIC_KEY_B64', None)
        old_env_prev = os.environ.pop('ZUBCUT_LICENSE_PUBLIC_KEY_B64_PREV', None)
        try:
            lo.LICENSE_PUBLIC_KEY_B64 = 'built-in-key'
            lo.LICENSE_PUBLIC_KEY_B64_PREV = ''
            tmp = tempfile.mkdtemp()
            lic = os.path.join(tmp, 'zubcut-license.json')
            lo.LICENSE_FILE_PATH = lic
            with open(lic, 'w', encoding='utf-8') as fh:
                import json
                json.dump({'verify_key_b64': 'stale-disk-key', 'payload': {}}, fh)
            self.assertEqual(lo._effective_public_key_b64(), 'built-in-key')
        finally:
            lo.LICENSE_PUBLIC_KEY_B64 = old
            lo.LICENSE_PUBLIC_KEY_B64_PREV = old_prev
            lo.LICENSE_FILE_PATH = old_path
            if old_env is None:
                os.environ.pop('ZUBCUT_LICENSE_PUBLIC_KEY_B64', None)
            else:
                os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64'] = old_env
            if old_env_prev is None:
                os.environ.pop('ZUBCUT_LICENSE_PUBLIC_KEY_B64_PREV', None)
            else:
                os.environ['ZUBCUT_LICENSE_PUBLIC_KEY_B64_PREV'] = old_env_prev

    def test_fetch_remote_verify_key(self) -> None:
        from tools import license_remote_signin as lrs

        sample_key = 'A' * 43 + '='

        class _Resp:
            def json(self):
                return {'ok': True, 'public_key_b64': sample_key}

        def _fake_get(url, **kwargs):
            return _Resp()

        orig = lrs.requests.get
        try:
            lrs.requests.get = _fake_get
            self.assertEqual(
                lrs.fetch_remote_verify_key_b64('https://example.test/signin'),
                sample_key,
            )
        finally:
            lrs.requests.get = orig


if __name__ == '__main__':
    unittest.main()
