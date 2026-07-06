import base64
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# PyInstaller analysis: trace cryptography native bindings (_rust) at freeze time.
try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except ImportError:
    pass

SIGNIN_PBKDF2_ITERS_DEFAULT = 100_000

# Pre-renaming on-disk license (migrated to LICENSE_FILE_PATH / zubcut-license.json on read).
_LEGACY_LICENSE_BASENAME = 'paid-license.json'

try:
    from constants import LICENSE_FILE_PATH, LICENSE_PUBLIC_KEY_B64
except Exception:
    _appdata = os.path.join(os.environ.get('APPDATA', ''), 'ZubCut')
    LICENSE_FILE_PATH = os.path.join(_appdata, 'zubcut-license.json')
    LICENSE_PUBLIC_KEY_B64 = ''


def _legacy_license_path() -> str:
    return os.path.join(os.path.dirname(LICENSE_FILE_PATH) or '.', _LEGACY_LICENSE_BASENAME)


def _maybe_migrate_legacy_license_file() -> None:
    """Move old license file beside zubcut-license.json if the new name is not present."""
    primary = LICENSE_FILE_PATH
    legacy = _legacy_license_path()
    try:
        if os.path.exists(primary) or not os.path.exists(legacy):
            return
        os.replace(legacy, primary)
    except OSError:
        pass


def _license_read_paths() -> list[str]:
    _maybe_migrate_legacy_license_file()
    out = [LICENSE_FILE_PATH]
    leg = _legacy_license_path()
    if leg and leg not in out:
        out.append(leg)
    return out


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


def _license_disk_verify_key() -> str:
    for path in _license_read_paths():
        if not path or not os.path.exists(path):
            continue
        try:
            data = json.load(open(path, 'r', encoding='utf-8'))
        except Exception:
            continue
        key = str(data.get('verify_key_b64') or '').strip()
        if key:
            return key
    return ''


def _effective_public_key_b64() -> str:
    return str(
        os.environ.get('ZUBCUT_LICENSE_PUBLIC_KEY_B64')
        or os.environ.get('ZUBCUT_PAID_PUBLIC_KEY_B64')
        or _license_disk_verify_key()
        or LICENSE_PUBLIC_KEY_B64
        or ''
    ).strip()


@dataclass
class LicenseValidationResult:
    ok: bool
    reason: str
    payload: dict[str, Any] | None = None
    signin_account: str = ''


def resolve_license_account(data: dict[str, Any] | None) -> str:
    """KV/sign-in account key: saved at sign-in, else payload user_name or account."""
    if not isinstance(data, dict):
        return ''
    top = str(data.get('signin_account') or '').strip().lower()
    if top:
        return top
    payload = data.get('payload')
    if isinstance(payload, dict):
        for key in ('user_name', 'account'):
            v = str(payload.get(key) or '').strip().lower()
            if v:
                return v
    return ''


def _build_stamp_for_errors() -> str:
    try:
        from constants import APP_BUILD_COMMIT, APP_BUILD_TIME_ISO, UPDATE_CHANNEL

        commit = str(APP_BUILD_COMMIT or '').strip()[:12]
        built = str(APP_BUILD_TIME_ISO or '').strip()
        channel = str(UPDATE_CHANNEL or '').strip()
        parts = [p for p in (channel, built, commit) if p]
        return f' (build {" · ".join(parts)})' if parts else ''
    except Exception:
        return ''


def _crypto_import_error() -> str | None:
    stamp = _build_stamp_for_errors()
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: F401
            Ed25519PublicKey,
        )
    except ImportError as e:
        return (
            'License verification is unavailable in this build (crypto library missing: '
            f'{e!r}). Reinstall from the latest ZubCut installer.'
            f'{stamp}'
        )
    except Exception as e:
        return f'License verification failed to load ({e!r}).{stamp}'
    return None


def license_crypto_self_test() -> tuple[bool, str]:
    """Frozen-build diagnostic (also used by CI via ZubCut.exe --verify-license-crypto)."""
    lines: list[str] = []
    if getattr(sys, 'frozen', False):
        lines.append(f'frozen=1 exe={sys.executable}')
        lines.append(f'_MEIPASS={getattr(sys, "_MEIPASS", "")}')
    else:
        lines.append('frozen=0')
    try:
        from constants import APP_BUILD_COMMIT, APP_BUILD_TIME_ISO, UPDATE_CHANNEL

        lines.append(f'channel={UPDATE_CHANNEL}')
        lines.append(f'built={APP_BUILD_TIME_ISO}')
        lines.append(f'commit={str(APP_BUILD_COMMIT or "")[:12]}')
        lines.append(f'verify_key_len={len(_effective_public_key_b64())}')
    except Exception as e:
        lines.append(f'constants_error={e}')
    if getattr(sys, 'frozen', False):
        internal = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), '_internal')
        lines.append(f'internal_exists={os.path.isdir(internal)}')
        rust_pyd = os.path.join(internal, 'cryptography', 'hazmat', 'bindings', '_rust.pyd')
        lines.append(f'cryptography_rust_pyd_exists={os.path.isfile(rust_pyd)}')
    err = _crypto_import_error()
    if err:
        return False, '\n'.join(lines + [f'FAIL: {err}'])
    lines.append('cryptography.ed25519: OK')
    return True, '\n'.join(lines + ['OK'])


def _verify_signature(payload: dict[str, Any], signature_b64: str, key_b64: str) -> bool:
    if not key_b64:
        return False
    if _crypto_import_error():
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        pk = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_b64))
        pk.verify(base64.b64decode(signature_b64), _canonical_payload_bytes(payload))
        return True
    except InvalidSignature:
        return False
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
    if not key_b64:
        return LicenseValidationResult(
            False,
            'This build has no license verify key. Install the official ZubCut build from GitHub.',
        )
    crypto_err = _crypto_import_error()
    if crypto_err:
        return LicenseValidationResult(False, crypto_err)
    if not _verify_signature(payload, signature, key_b64):
        return LicenseValidationResult(
            False,
            'License signature invalid. Ask your admin to re-push your account in License Manager, '
            'or install the latest official ZubCut build.',
        )
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


def install_license_document(
    data: dict[str, Any],
    *,
    signin_account: str | None = None,
    verify_key_b64: str | None = None,
) -> None:
    """Write validated license JSON to the installed license path."""
    out = dict(data)
    acct = str(signin_account or out.get('signin_account') or '').strip().lower()
    if acct:
        out['signin_account'] = acct
    key = str(
        verify_key_b64
        or out.get('verify_key_b64')
        or _effective_public_key_b64()
        or ''
    ).strip()
    if key:
        out['verify_key_b64'] = key
    os.makedirs(os.path.dirname(LICENSE_FILE_PATH) or '.', exist_ok=True)
    with open(LICENSE_FILE_PATH, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2)


def load_and_validate_installed_license(path: str | None = None) -> LicenseValidationResult:
    if path:
        candidates = [path]
    else:
        candidates = [p for p in _license_read_paths() if p]
    lic_path = ''
    for cand in candidates:
        if cand and os.path.exists(cand):
            lic_path = cand
            break
    if not lic_path:
        return LicenseValidationResult(False, 'License file missing')
    try:
        data = json.load(open(lic_path, 'r', encoding='utf-8'))
    except Exception:
        return LicenseValidationResult(False, 'License file unreadable')

    acct = resolve_license_account(data)
    res = validate_license_document(data)
    return LicenseValidationResult(res.ok, res.reason, res.payload, signin_account=acct)
