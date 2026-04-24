import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from nacl.signing import SigningKey

from constants import (
    PAID_LICENSE_ADMIN_DB_PATH,
    PAID_LICENSE_ADMIN_SIGNING_KEY_PATH,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


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


def _load_signing_key() -> SigningKey:
    os.makedirs(os.path.dirname(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH), exist_ok=True)
    if os.path.exists(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH):
        raw = open(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH, 'rb').read()
        return SigningKey(raw)
    key = SigningKey.generate()
    open(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH, 'wb').write(bytes(key))
    return key


def admin_public_verify_key_b64() -> str:
    key = _load_signing_key()
    return base64.b64encode(bytes(key.verify_key)).decode('ascii')


def _license_record_schema() -> dict[str, Any]:
    return {'version': 1, 'licenses': []}


def load_license_db() -> dict[str, Any]:
    os.makedirs(os.path.dirname(PAID_LICENSE_ADMIN_DB_PATH), exist_ok=True)
    if not os.path.exists(PAID_LICENSE_ADMIN_DB_PATH):
        return _license_record_schema()
    try:
        data = json.load(open(PAID_LICENSE_ADMIN_DB_PATH, 'r', encoding='utf-8'))
    except Exception:
        return _license_record_schema()
    if not isinstance(data, dict):
        return _license_record_schema()
    if not isinstance(data.get('licenses'), list):
        data['licenses'] = []
    data.setdefault('version', 1)
    return data


def save_license_db(db: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(PAID_LICENSE_ADMIN_DB_PATH), exist_ok=True)
    with open(PAID_LICENSE_ADMIN_DB_PATH, 'w', encoding='utf-8') as fh:
        json.dump(db, fh, indent=2)


def _sign_in_password_fields(sign_in_password: str) -> dict[str, str]:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac(
        'sha256',
        str(sign_in_password).encode('utf-8'),
        salt,
        210_000,
    )
    return {
        'password_salt': base64.b64encode(salt).decode('ascii'),
        'password_hash': h.hex(),
    }


def _signed_document(payload: dict[str, Any]) -> dict[str, Any]:
    key = _load_signing_key()
    sig = key.sign(_canonical_payload_bytes(payload)).signature
    return {
        'payload': payload,
        'signature': base64.b64encode(sig).decode('ascii'),
    }


def create_license(
    user_name: str,
    duration_days: int,
    device_hash: str = '',
    sign_in_password: str | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    payload = {
        'license_id': str(uuid.uuid4()),
        'user_name': str(user_name or '').strip(),
        'issued_at': _iso(now),
        'expires_at': _iso(now + timedelta(days=max(1, int(duration_days)))),
        'device_hash': str(device_hash or '').strip(),
        'status': 'active',
    }
    pwd = str(sign_in_password or '').strip()
    if pwd:
        payload.update(_sign_in_password_fields(pwd))
    doc = _signed_document(payload)
    rec = {
        'payload': payload,
        'signature': doc['signature'],
        'created_at': _iso(now),
        'updated_at': _iso(now),
    }
    db = load_license_db()
    db['licenses'].append(rec)
    save_license_db(db)
    return rec


def renew_license(license_id: str, extend_days: int) -> dict[str, Any] | None:
    db = load_license_db()
    now = _utc_now()
    for rec in db['licenses']:
        p = rec.get('payload') or {}
        if p.get('license_id') != license_id:
            continue
        try:
            old_exp = _parse_iso_utc(str(p.get('expires_at')))
        except Exception:
            old_exp = now
        base = old_exp if old_exp > now else now
        p['expires_at'] = _iso(base + timedelta(days=max(1, int(extend_days))))
        p['status'] = 'active'
        signed = _signed_document(p)
        rec['payload'] = p
        rec['signature'] = signed['signature']
        rec['updated_at'] = _iso(now)
        save_license_db(db)
        return rec
    return None


def set_license_status(license_id: str, status: str) -> dict[str, Any] | None:
    db = load_license_db()
    now = _utc_now()
    status = str(status or 'active').strip().lower()
    if status not in ('active', 'revoked'):
        status = 'active'
    for rec in db['licenses']:
        p = rec.get('payload') or {}
        if p.get('license_id') != license_id:
            continue
        p['status'] = status
        signed = _signed_document(p)
        rec['payload'] = p
        rec['signature'] = signed['signature']
        rec['updated_at'] = _iso(now)
        save_license_db(db)
        return rec
    return None


def delete_license(license_id: str) -> bool:
    """Remove one license from the admin database. Returns False if id not found."""
    db = load_license_db()
    licenses = db.get('licenses')
    if not isinstance(licenses, list):
        return False
    nid = str(license_id or '').strip()
    new_list = [rec for rec in licenses if str((rec.get('payload') or {}).get('license_id') or '') != nid]
    if len(new_list) == len(licenses):
        return False
    db['licenses'] = new_list
    save_license_db(db)
    return True


def signed_document_for_license_id(license_id: str) -> dict[str, Any] | None:
    """Return {\"payload\": ..., \"signature\": ...} for encoding / export."""
    db = load_license_db()
    for rec in db['licenses']:
        p = rec.get('payload') or {}
        if p.get('license_id') != license_id:
            continue
        return {'payload': p, 'signature': str(rec.get('signature', ''))}
    return None


def cloud_kv_bundle_for_license_id(license_id: str) -> dict[str, Any] | None:
    """
    JSON object to store as the Worker KV *value* for free-tier online sign-in.

    KV *key* should be the account name in lowercase (see ``cloud_kv_key_for_account``).
    Requires a sign-in password on the license (PBKDF2 fields in payload).
    """
    doc = signed_document_for_license_id(license_id)
    if doc is None:
        return None
    p = doc.get('payload') or {}
    ph = str(p.get('password_hash') or '').strip()
    salt = str(p.get('password_salt') or '').strip()
    if not ph or not salt:
        return None
    return {
        'version': 1,
        'password_salt': salt,
        'password_hash_hex': ph,
        'license': doc,
    }


def cloud_kv_key_for_account(user_name: str) -> str:
    """KV lookup key: lowercase trimmed account name (must match ZubCut sign-in)."""
    return str(user_name or '').strip().casefold()


def export_cloud_kv_bundle(license_id: str, out_path: str) -> bool:
    """Write KV bundle JSON for Wrangler / dashboard upload."""
    bundle = cloud_kv_bundle_for_license_id(license_id)
    if bundle is None:
        return False
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(bundle, fh, indent=2)
    return True


def list_license_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    rows = []
    for rec in load_license_db().get('licenses', []):
        p = rec.get('payload') or {}
        lic_id = str(p.get('license_id') or '')
        if not lic_id:
            continue
        user = str(p.get('user_name') or '').strip() or '(unnamed)'
        status = str(p.get('status') or 'active').strip().lower()
        expires_raw = str(p.get('expires_at') or '')
        try:
            exp = _parse_iso_utc(expires_raw)
            remaining_sec = int((exp - now).total_seconds())
        except Exception:
            remaining_sec = -1
        rows.append(
            {
                'license_id': lic_id,
                'user_name': user,
                'status': status,
                'expires_at': expires_raw,
                'remaining_sec': remaining_sec,
                'device_hash': str(p.get('device_hash') or '').strip(),
            }
        )
    rows.sort(key=lambda r: (r['status'] != 'active', r['remaining_sec']))
    return rows

