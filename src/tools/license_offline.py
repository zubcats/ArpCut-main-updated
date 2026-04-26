import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SIGNIN_PBKDF2_ITERS_DEFAULT = 100_000

try:
    from constants import PAID_LICENSE_FILE_PATH, PAID_LICENSE_PUBLIC_KEY_B64
except Exception:
    # Backward compatibility for builds with older constants modules.
    from constants import DOCUMENTS_PATH

    PAID_LICENSE_FILE_PATH = os.path.join(DOCUMENTS_PATH, 'paid-license.json')
    PAID_LICENSE_PUBLIC_KEY_B64 = ''


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_utc(value: str) -> datetime:
    v = str(value or '').strip()
    if v.endswith('Z'):
        v = v[:-1] + '+00:00'
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _effective_public_key_b64() -> str:
    return str(
        os.environ.get('ZUBCUT_PAID_PUBLIC_KEY_B64')
        or PAID_LICENSE_PUBLIC_KEY_B64
        or ''
    ).strip()


@dataclass
class LicenseValidationResult:
    ok: bool
    reason: str
    payload: dict[str, Any] | None = None


def _verify_signature(payload: dict[str, Any], signature_b64: str, key_b64: str) -> bool:
    if not key_b64:
        return False
    try:
        from nacl.signing import VerifyKey
    except Exception:
        return False
    try:
        verify_key = VerifyKey(base64.b64decode(key_b64))
        verify_key.verify(_canonical_payload_bytes(payload), base64.b64decode(signature_b64))
        return True
    except Exception:
        return False


def _sign_in_password_ok(payload: dict[str, Any], sign_in_password: str | None) -> tuple[bool, str]:
    ph = str(payload.get('password_hash') or '').strip()
    if not ph:
        return True, ''
    pwd = str(sign_in_password or '').strip()
    if not pwd:
        return False, 'Wrong password'
    salt_b64 = str(payload.get('password_salt') or '').strip()
    if not salt_b64:
        return False, 'License is missing password data'
    try:
        salt = base64.b64decode(salt_b64)
    except Exception:
        return False, 'License is missing password data'
    try:
        iters = int(payload.get('password_iters') or SIGNIN_PBKDF2_ITERS_DEFAULT)
    except Exception:
        iters = SIGNIN_PBKDF2_ITERS_DEFAULT
    if iters < 1:
        iters = SIGNIN_PBKDF2_ITERS_DEFAULT
    calc = hashlib.pbkdf2_hmac('sha256', pwd.encode('utf-8'), salt, iters).hex()
    if calc != ph:
        return False, 'Wrong password'
    return True, ''


def validate_license_document(
    data: dict[str, Any],
    *,
    sign_in_password: str | None = None,
) -> LicenseValidationResult:
    """Validate a signed license dict (payload + signature).

    When ``sign_in_password`` is not None, also checks PBKDF2 password if the payload has ``password_hash``.
    Startup validation omits this so the saved file keeps working after first sign-in.
    """
    if not isinstance(data, dict):
        return LicenseValidationResult(False, 'License format invalid')
    payload = data.get('payload')
    signature = data.get('signature')
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return LicenseValidationResult(False, 'License payload/signature missing')
    key_b64 = _effective_public_key_b64()
    # No-key mode: if no verify key is configured, trust server-delivered payload
    # and rely on password, status, expiry, and optional device binding checks.
    if key_b64 and (not _verify_signature(payload, signature, key_b64)):
        return LicenseValidationResult(False, 'License signature invalid')
    if str(payload.get('status', 'active')).strip().lower() != 'active':
        return LicenseValidationResult(False, 'License not active', payload=payload)

    expires_at_raw = payload.get('expires_at')
    if not expires_at_raw:
        return LicenseValidationResult(False, 'License expires_at missing')
    try:
        expires_at = _parse_iso_utc(str(expires_at_raw))
    except Exception:
        return LicenseValidationResult(False, 'License expires_at invalid')
    if _utc_now() > expires_at:
        return LicenseValidationResult(False, 'License expired', payload=payload)

    if sign_in_password is not None:
        ok, reason = _sign_in_password_ok(payload, sign_in_password)
        if not ok:
            return LicenseValidationResult(False, reason, payload=payload)

    return LicenseValidationResult(True, 'License valid', payload=payload)


def install_license_document(data: dict[str, Any]) -> None:
    """Write validated license JSON to the installed license path."""
    os.makedirs(os.path.dirname(PAID_LICENSE_FILE_PATH) or '.', exist_ok=True)
    with open(PAID_LICENSE_FILE_PATH, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)


def load_and_validate_installed_license(path: str | None = None) -> LicenseValidationResult:
    lic_path = path or PAID_LICENSE_FILE_PATH
    if not os.path.exists(lic_path):
        return LicenseValidationResult(False, 'License file missing')
    try:
        data = json.load(open(lic_path, 'r', encoding='utf-8'))
    except Exception:
        return LicenseValidationResult(False, 'License file unreadable')

    return validate_license_document(data)
