"""Sign licenses and build KV bundles (matches Cloudflare worker PBKDF2)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from license_manager.constants import SIGNIN_PBKDF2_ITERS_DEFAULT


def _utc_iso(dt: datetime | None = None) -> str:
    when = dt or datetime.now(timezone.utc)
    return when.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_private_key(path: str) -> Ed25519PrivateKey:
    raw = open(path, 'rb').read()
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except Exception:
        key = serialization.load_der_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Private key must be Ed25519')
    return key


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(pub).decode('ascii')


def pbkdf2_sha256_hex(password: str, salt_b64: str, iterations: int = SIGNIN_PBKDF2_ITERS_DEFAULT) -> str:
    salt = base64.b64decode(salt_b64)
    iters = max(1, min(int(iterations or SIGNIN_PBKDF2_ITERS_DEFAULT), SIGNIN_PBKDF2_ITERS_DEFAULT))
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iters).hex()


def make_password_fields(password: str) -> dict[str, Any]:
    salt = os.urandom(16)
    salt_b64 = base64.b64encode(salt).decode('ascii')
    return {
        'password_salt': salt_b64,
        'password_hash_hex': pbkdf2_sha256_hex(password, salt_b64),
        'password_iters': SIGNIN_PBKDF2_ITERS_DEFAULT,
    }


def sign_license_payload(payload: dict[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    msg = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    sig = private_key.sign(msg)
    return {
        'payload': payload,
        'signature': base64.b64encode(sig).decode('ascii'),
    }


def build_account_license(
    *,
    account_key: str,
    password: str,
    private_key: Ed25519PrivateKey,
    days: int = 30,
    status: str = 'active',
    license_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (kv_bundle, local_account_record)."""
    pwd_fields = make_password_fields(password)
    expires = datetime.now(timezone.utc) + timedelta(days=max(1, int(days)))
    payload = {
        'license_id': license_id or str(uuid.uuid4()),
        'user_name': account_key,
        'account': account_key,
        'status': status,
        'expires_at': _utc_iso(expires),
        'password_salt': pwd_fields['password_salt'],
        'password_hash': pwd_fields['password_hash_hex'],
        'password_iters': pwd_fields['password_iters'],
    }
    license_doc = sign_license_payload(payload, private_key)
    bundle = {
        'password_salt': pwd_fields['password_salt'],
        'password_hash_hex': pwd_fields['password_hash_hex'],
        'password_iters': pwd_fields['password_iters'],
        'license': license_doc,
    }
    local = {
        'account_key': account_key,
        'status': status,
        'expires_at': payload['expires_at'],
        'license_id': payload['license_id'],
        'license': license_doc,
        'password_salt': pwd_fields['password_salt'],
        'password_hash_hex': pwd_fields['password_hash_hex'],
        'password_iters': pwd_fields['password_iters'],
        'updated_at': _utc_iso(),
    }
    return bundle, local


def renew_account_license(
    record: dict[str, Any],
    *,
    private_key: Ed25519PrivateKey,
    days: int = 30,
    password: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    account_key = str(record.get('account_key') or '').strip().lower()
    status = str(record.get('status') or 'active')
    license_id = str(record.get('license_id') or '')
    if password:
        pwd_fields = make_password_fields(password)
    else:
        pwd_fields = {
            'password_salt': record.get('password_salt'),
            'password_hash_hex': record.get('password_hash_hex'),
            'password_iters': record.get('password_iters', SIGNIN_PBKDF2_ITERS_DEFAULT),
        }
    expires = datetime.now(timezone.utc) + timedelta(days=max(1, int(days)))
    payload = {
        'license_id': license_id or str(uuid.uuid4()),
        'user_name': account_key,
        'account': account_key,
        'status': status,
        'expires_at': _utc_iso(expires),
        'password_salt': pwd_fields['password_salt'],
        'password_hash': pwd_fields['password_hash_hex'],
        'password_iters': pwd_fields['password_iters'],
    }
    license_doc = sign_license_payload(payload, private_key)
    bundle = {
        'password_salt': pwd_fields['password_salt'],
        'password_hash_hex': pwd_fields['password_hash_hex'],
        'password_iters': pwd_fields['password_iters'],
        'license': license_doc,
    }
    local = dict(record)
    local.update(
        {
            'account_key': account_key,
            'status': status,
            'expires_at': payload['expires_at'],
            'license_id': payload['license_id'],
            'license': license_doc,
            'password_salt': pwd_fields['password_salt'],
            'password_hash_hex': pwd_fields['password_hash_hex'],
            'password_iters': pwd_fields['password_iters'],
            'updated_at': _utc_iso(),
        }
    )
    return bundle, local


def set_account_status(
    record: dict[str, Any],
    *,
    private_key: Ed25519PrivateKey,
    status: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    account_key = str(record.get('account_key') or '').strip().lower()
    license_doc = record.get('license') or {}
    payload = dict(license_doc.get('payload') or {})
    payload['status'] = status
    signed = sign_license_payload(payload, private_key)
    bundle = {
        'password_salt': record.get('password_salt'),
        'password_hash_hex': record.get('password_hash_hex'),
        'password_iters': record.get('password_iters', SIGNIN_PBKDF2_ITERS_DEFAULT),
        'license': signed,
    }
    local = dict(record)
    local['status'] = status
    local['license'] = signed
    local['expires_at'] = payload.get('expires_at', local.get('expires_at', ''))
    local['updated_at'] = _utc_iso()
    local['account_key'] = account_key
    return bundle, local
