import base64
import hashlib
import json
import os
import platform
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from constants import PAID_LICENSE_FILE_PATH, PAID_LICENSE_PUBLIC_KEY_B64


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


def current_device_hash() -> str:
    """
    Stable-ish machine fingerprint for optional license binding.
    This is not hardware-tamper proof; it is only a sharing deterrent.
    """
    parts = [
        platform.system(),
        platform.node(),
        platform.machine(),
        platform.processor(),
        hex(uuid.getnode()),
    ]
    raw = '|'.join(parts).encode('utf-8', errors='ignore')
    return hashlib.sha256(raw).hexdigest()


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')


@dataclass
class LicenseValidationResult:
    ok: bool
    reason: str
    payload: dict[str, Any] | None = None


def _verify_signature(payload: dict[str, Any], signature_b64: str) -> bool:
    key_b64 = str(PAID_LICENSE_PUBLIC_KEY_B64 or '').strip()
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


def load_and_validate_installed_license(path: str | None = None) -> LicenseValidationResult:
    lic_path = path or PAID_LICENSE_FILE_PATH
    if not os.path.exists(lic_path):
        return LicenseValidationResult(False, 'License file missing')
    try:
        data = json.load(open(lic_path, 'r', encoding='utf-8'))
    except Exception:
        return LicenseValidationResult(False, 'License file unreadable')

    if not isinstance(data, dict):
        return LicenseValidationResult(False, 'License format invalid')
    payload = data.get('payload')
    signature = data.get('signature')
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return LicenseValidationResult(False, 'License payload/signature missing')
    if not _verify_signature(payload, signature):
        return LicenseValidationResult(False, 'License signature invalid')

    expires_at_raw = payload.get('expires_at')
    if not expires_at_raw:
        return LicenseValidationResult(False, 'License expires_at missing')
    try:
        expires_at = _parse_iso_utc(str(expires_at_raw))
    except Exception:
        return LicenseValidationResult(False, 'License expires_at invalid')
    if _utc_now() > expires_at:
        return LicenseValidationResult(False, 'License expired', payload=payload)

    bound_device = str(payload.get('device_hash') or '').strip()
    if bound_device and bound_device != current_device_hash():
        return LicenseValidationResult(False, 'License device mismatch', payload=payload)

    return LicenseValidationResult(True, 'License valid', payload=payload)
