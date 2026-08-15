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

SIGNIN_PBKDF2_ITERS = 100_000


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


def _load_signing_key(*, allow_generate: bool | None = None) -> SigningKey:
    """
    Load the Control Panel Ed25519 signing key.

    If the key file is missing and the admin DB already has licenses, refuse to
    auto-generate a new key (that would break renewals vs the public key baked
    into ZubCut builds). First-time bootstrap (empty DB) may still generate.
    """
    os.makedirs(os.path.dirname(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH), exist_ok=True)
    if os.path.exists(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH):
        raw = open(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH, 'rb').read()
        try:
            from tools.secret_store import unprotect_bytes

            raw = unprotect_bytes(raw)
        except Exception:
            pass
        return SigningKey(raw)
    if allow_generate is None:
        try:
            allow_generate = not bool(load_license_db().get('licenses'))
        except Exception:
            allow_generate = True
    if not allow_generate:
        raise FileNotFoundError(
            'Signing key is missing (%s). Restore paid-license-signing.key from backup, '
            'or use Rotate signing key (keep existing accounts) after a dual-key ZubCut '
            'build is shipping — a silent new key would not match already-installed builds.'
            % PAID_LICENSE_ADMIN_SIGNING_KEY_PATH
        )
    key = SigningKey.generate()
    blob = bytes(key)
    try:
        from tools.secret_store import protect_bytes, restrict_user_only_acl

        blob = protect_bytes(blob)
        open(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH, 'wb').write(blob)
        restrict_user_only_acl(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH)
    except Exception:
        open(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH, 'wb').write(bytes(key))
    return key


def signing_key_file_present() -> bool:
    return os.path.isfile(PAID_LICENSE_ADMIN_SIGNING_KEY_PATH)


def admin_public_verify_key_b64() -> str:
    key = _load_signing_key()
    return base64.b64encode(bytes(key.verify_key)).decode('ascii')


def rewrap_signing_key() -> tuple[bool, str]:
    """Re-DPAPI-protect the existing signing key file for the current Windows user."""
    path = PAID_LICENSE_ADMIN_SIGNING_KEY_PATH
    if not os.path.exists(path):
        return False, 'No signing key file yet — create a license first.'
    try:
        raw = open(path, 'rb').read()
    except OSError as exc:
        return False, f'Could not read signing key: {exc}'
    try:
        from tools.secret_store import rewrap_bytes, restrict_user_only_acl

        new_raw, note = rewrap_bytes(raw)
        if note == 'decrypt_failed':
            return False, 'Could not decrypt signing key (wrong Windows user?).'
        if note == 'encrypt_failed':
            return False, 'DPAPI encrypt failed — signing key left unchanged.'
        open(path, 'wb').write(new_raw)
        restrict_user_only_acl(path)
        return True, 'Signing key re-protected with DPAPI for this Windows user.'
    except Exception as exc:
        return False, f'Re-protect failed: {exc}'


def rotate_signing_key(*, re_sign_licenses: bool = True) -> tuple[bool, str, str]:
    """
    Generate a new Ed25519 signing key (DPAPI-wrapped) and optionally re-sign all licenses.

    Returns (ok, message, new_public_key_b64). Set GitHub secret LICENSE_PUBLIC_KEY_B64
    to the new pubkey and keep PAID_LICENSE_PUBLIC_KEY_B64 as the previous verify key.
    """
    path = PAID_LICENSE_ADMIN_SIGNING_KEY_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = SigningKey.generate()
    blob = bytes(key)
    try:
        from tools.secret_store import protect_bytes, restrict_user_only_acl

        blob = protect_bytes(blob)
        open(path, 'wb').write(blob)
        restrict_user_only_acl(path)
    except Exception:
        open(path, 'wb').write(bytes(key))
    pub = base64.b64encode(bytes(key.verify_key)).decode('ascii')
    if re_sign_licenses:
        n = re_sign_all_licenses()
        return (
            True,
            f'New signing key saved. Re-signed {n} license(s). '
            'Set GitHub secret LICENSE_PUBLIC_KEY_B64 to the new public key, keep '
            'PAID_LICENSE_PUBLIC_KEY_B64 as the previous key, and rebuild ZubCut.',
            pub,
        )
    return (
        True,
        'New signing key saved. Existing accounts were left on the old signatures '
        '(they keep working on current installs). New and renewed accounts need a '
        'ZubCut build that includes both verify keys. Set GitHub secret '
        'LICENSE_PUBLIC_KEY_B64 to the new public key and leave '
        'PAID_LICENSE_PUBLIC_KEY_B64 unchanged.',
        pub,
    )


def re_sign_all_licenses() -> int:
    """Re-sign every license payload with the current signing key. Returns count."""
    db = load_license_db()
    now = _utc_now()
    count = 0
    for rec in db.get('licenses') or []:
        p = rec.get('payload')
        if not isinstance(p, dict):
            continue
        signed = _signed_document(p)
        rec['payload'] = p
        rec['signature'] = signed['signature']
        rec['updated_at'] = _iso(now)
        count += 1
    if count:
        save_license_db(db)
    return count


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
        SIGNIN_PBKDF2_ITERS,
    )
    return {
        'password_salt': base64.b64encode(salt).decode('ascii'),
        'password_hash': h.hex(),
        'password_iters': SIGNIN_PBKDF2_ITERS,
    }


def _signed_document(payload: dict[str, Any]) -> dict[str, Any]:
    key = _load_signing_key()
    sig = key.sign(_canonical_payload_bytes(payload)).signature
    return {
        'payload': payload,
        'signature': base64.b64encode(sig).decode('ascii'),
    }


def _duration_minutes(duration_days: int | None = None, duration_minutes: int | None = None) -> int:
    if duration_minutes is not None:
        return max(1, int(duration_minutes))
    return max(1, int(duration_days or 1)) * 24 * 60


def create_license(
    user_name: str,
    duration_days: int,
    device_hash: str = '',
    sign_in_password: str | None = None,
    *,
    duration_minutes: int | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    dur_min = _duration_minutes(duration_days, duration_minutes)
    payload = {
        'license_id': str(uuid.uuid4()),
        'user_name': str(user_name or '').strip(),
        'issued_at': _iso(now),
        'expires_at': _iso(now + timedelta(minutes=dur_min)),
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


def renew_license(
    license_id: str,
    extend_days: int,
    *,
    extend_minutes: int | None = None,
) -> dict[str, Any] | None:
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
        ext_min = _duration_minutes(extend_days, extend_minutes)
        p['expires_at'] = _iso(base + timedelta(minutes=ext_min))
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
        'password_iters': int(p.get('password_iters') or SIGNIN_PBKDF2_ITERS),
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


def import_license_records_from_kv_bundles(bundles: list[dict[str, Any]]) -> tuple[int, int]:
    """
    Merge Cloudflare KV account bundles into the local admin DB.

    Returns (imported_or_updated, skipped). Does not require the signing key —
    signatures from the cloud bundles are kept as-is.
    """
    db = load_license_db()
    by_id: dict[str, dict[str, Any]] = {}
    for rec in db.get('licenses') or []:
        if not isinstance(rec, dict):
            continue
        lid = str((rec.get('payload') or {}).get('license_id') or '').strip()
        if lid:
            by_id[lid] = rec
    imported = 0
    skipped = 0
    for bundle in bundles:
        if not isinstance(bundle, dict):
            skipped += 1
            continue
        lic = bundle.get('license')
        if not isinstance(lic, dict):
            skipped += 1
            continue
        payload = dict(lic.get('payload') or {})
        if not payload.get('license_id'):
            skipped += 1
            continue
        if not payload.get('password_hash') and bundle.get('password_hash_hex'):
            payload['password_hash'] = bundle.get('password_hash_hex')
        if not payload.get('password_salt') and bundle.get('password_salt'):
            payload['password_salt'] = bundle.get('password_salt')
        if bundle.get('password_iters') and not payload.get('password_iters'):
            payload['password_iters'] = bundle.get('password_iters')
        sig = str(lic.get('signature') or '')
        lid = str(payload.get('license_id'))
        rec = {
            'payload': payload,
            'signature': sig,
            'created_at': str(payload.get('issued_at') or ''),
            'updated_at': str(payload.get('issued_at') or ''),
        }
        by_id[lid] = rec
        imported += 1
    db['licenses'] = list(by_id.values())
    save_license_db(db)
    return imported, skipped


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
            exp = None
            remaining_sec = -1
        expired_days = None
        if exp is not None and remaining_sec < 0:
            expired_days = max(0, int((now - exp).total_seconds() // 86400))
        rows.append(
            {
                'license_id': lic_id,
                'user_name': user,
                'status': status,
                'expires_at': expires_raw,
                'remaining_sec': remaining_sec,
                'expired_days': expired_days,
                'device_hash': str(p.get('device_hash') or '').strip(),
            }
        )
    rows.sort(key=lambda r: (r['status'] != 'active', r['remaining_sec']))
    return rows

