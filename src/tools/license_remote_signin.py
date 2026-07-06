"""
License sign-in: POST account + password to a HTTPS endpoint; response includes the signed license document.

Used with the Cloudflare Worker in backend/cloudflare-license-signin/.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


def license_transient_reason(reason: str) -> str:
    """Collapse transport/DNS errors into a single user-facing line."""
    s = str(reason or '').strip()
    if not s:
        return 'License server unreachable (will retry).'
    low = s.casefold()
    if any(
        token in low
        for token in (
            'getaddrinfo',
            'name resolution',
            'failed to resolve',
            'nameresolutionerror',
        )
    ):
        return 'Offline — cannot resolve license server (check internet/DNS). Will retry.'
    if 'timed out' in low or 'timeout' in low:
        return 'License server timed out. Will retry.'
    if 'could not reach' in low or 'max retries exceeded' in low:
        return 'License server unreachable. Will retry.'
    if 'connection refused' in low or 'connection aborted' in low:
        return 'License server unreachable. Will retry.'
    if len(s) > 100:
        return s[:97] + '...'
    return s


def normalize_signin_base_url(url: str) -> str:
    """Strip trailing /validate so sign-in POST hits the root handler, not session validate."""
    base = str(url or '').strip()
    if not base:
        return ''
    try:
        parts = urlsplit(base)
        p = (parts.path or '/').rstrip('/')
        if p.lower().endswith('/validate'):
            p = p[: -len('/validate')].rstrip('/')
        path = '' if not p or p == '/' else p
        return urlunsplit((parts.scheme, parts.netloc, path, '', ''))
    except Exception:
        trimmed = base.rstrip('/')
        if trimmed.lower().endswith('/validate'):
            trimmed = trimmed[: -len('/validate')].rstrip('/')
        return trimmed


def _verify_key_hint() -> str:
    try:
        from tools.license_offline import _effective_public_key_b64

        key = _effective_public_key_b64()
        if not key:
            return 'verify_key=missing'
        return f'verify_key_len={len(key)} verify_key_tail={key[-8:]}'
    except Exception as e:
        return f'verify_key_error={e!r}'


def _build_stamp_line() -> str:
    try:
        from constants import APP_BUILD_COMMIT, APP_BUILD_TIME_ISO, UPDATE_CHANNEL

        commit = str(APP_BUILD_COMMIT or '').strip()[:12]
        built = str(APP_BUILD_TIME_ISO or '').strip()
        channel = str(UPDATE_CHANNEL or '').strip()
        parts = [p for p in (channel, built, commit) if p]
        return ' · '.join(parts) if parts else 'unknown build'
    except Exception:
        return 'unknown build'


def write_signin_diagnostic(
    *,
    step: str,
    account: str = '',
    error: str = '',
    extra: dict[str, Any] | None = None,
) -> str:
    """Append a sign-in attempt record to %TEMP%\\ZubCut-signin-last.log for support."""
    path = os.path.join(tempfile.gettempdir(), 'ZubCut-signin-last.log')
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    lines = [
        f'[{stamp}] step={step}',
        f'build={_build_stamp_line()}',
        f'account={account or "(none)"}',
        f'error={error or "(none)"}',
        _verify_key_hint(),
    ]
    url = effective_signin_url()
    if url:
        lines.append(f'signin_url={normalize_signin_base_url(url)}')
    else:
        lines.append('signin_url=missing')
    if extra:
        for k, v in extra.items():
            lines.append(f'{k}={v}')
    lines.append('')
    try:
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write('\n'.join(lines))
    except OSError:
        pass
    return path


def signin_failure_hint(reason: str) -> str:
    """Short remediation line appended to user-facing sign-in errors."""
    low = str(reason or '').casefold()
    if 'signature invalid' in low:
        return (
            'The server accepted your password but this ZubCut build cannot verify the license signature. '
            'Reinstall the latest official ZubCut build, or confirm the build was made with the correct '
            'LICENSE_PUBLIC_KEY_B64.'
        )
    if 'missing sign-in server url' in low or 'sign-in url is not configured' in low:
        return (
            'Set Windows environment variable ZUBCUT_LICENSE_SIGNIN_URL to '
            'https://zubcut-license-signin.zubcats.workers.dev then restart ZubCut.'
        )
    if 'verify key' in low and 'missing' in low:
        return 'Reinstall the latest official ZubCut build.'
    if 'invalid credentials' in low:
        return (
            'Double-check account name (lowercase) and password. If correct, ask admin to use '
            'License Manager → Push selected to cloud for your account.'
        )
    if 're-push your account' in low:
        return 'Admin: open License Manager, select the account, click Push selected to cloud.'
    if 'expired' in low:
        return 'Ask your administrator to renew your subscription in License Manager.'
    return ''


def effective_signin_url() -> str:
    """HTTPS license server URL (empty if not configured)."""
    try:
        from constants import LICENSE_SIGNIN_URL
    except Exception:
        LICENSE_SIGNIN_URL = ''
    raw = (
        str(
            os.environ.get('ZUBCUT_LICENSE_SIGNIN_URL')
            or os.environ.get('ZUBCUT_PAID_SIGNIN_URL')
            or LICENSE_SIGNIN_URL
            or ''
        ).strip()
    )
    return normalize_signin_base_url(raw)


def fetch_remote_verify_key_b64(url: str, *, timeout_sec: float = 12.0) -> str:
    """Optional: GET /public-key if the deployed worker supports it (not required)."""
    base = normalize_signin_base_url(url)
    if not base:
        return ''
    purl = f'{base.rstrip("/")}/public-key'
    try:
        r = requests.get(purl, timeout=timeout_sec)
    except requests.RequestException:
        return ''
    try:
        body = r.json()
    except Exception:
        return ''
    if not isinstance(body, dict) or not body.get('ok'):
        return ''
    key = str(body.get('public_key_b64') or '').strip()
    # Ignore health-check JSON from workers without /public-key.
    if not key or len(key) < 40:
        return ''
    return key


def ensure_signin_verify_key(signin_url: str | None = None) -> tuple[bool, str]:
    """Return True when a verify key is available locally (no server fetch)."""
    try:
        from tools.license_offline import _effective_public_key_b64
    except Exception:
        return False, 'License module unavailable'
    if _effective_public_key_b64():
        return True, ''
    return False, 'Missing license verify key in this build'


def fetch_license_document_via_signin(
    url: str,
    account: str,
    password: str,
    *,
    timeout_sec: float = 30.0,
) -> tuple[dict[str, Any] | None, str]:
    """
    POST ``{"account","password"}`` to the given HTTPS URL; expect JSON
    ``{"ok": true, "license": {"payload", "signature"}}`` or ``{"ok": false, "error": "..."}``.
    """
    base = str(url or '').strip()
    if not base:
        return None, 'Sign-in URL is not configured.'
    account = str(account or '').strip().lower()
    if not account:
        return None, 'Enter your account name.'
    if not str(password or ''):
        return None, 'Enter your password.'
    try:
        r = requests.post(
            base,
            json={'account': account, 'password': password},
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            timeout=timeout_sec,
        )
    except requests.RequestException as e:
        return None, license_transient_reason(str(e))

    try:
        body = r.json()
    except Exception:
        return None, f'Sign-in server returned an unexpected response (HTTP {r.status_code}).'

    if not isinstance(body, dict):
        return None, 'Sign-in server returned an unexpected response.'

    if not body.get('ok'):
        err = str(body.get('error') or body.get('message') or 'Sign-in failed').strip()
        return None, err or 'Sign-in failed.'

    lic = body.get('license')
    if not isinstance(lic, dict):
        return None, 'Sign-in server did not return a license.'

    return lic, ''


def probe_signin_configuration(*, timeout_sec: float = 12.0) -> tuple[bool, str]:
    """Lightweight support probe (no password). Writes ZubCut-signin-last.log on failure paths."""
    from tools.license_offline import _effective_public_key_b64

    lines: list[str] = []
    url = effective_signin_url()
    lines.append(f'signin_url={url or "(missing)"}')
    lines.append(_verify_key_hint())
    lines.append(f'build={_build_stamp_line()}')
    if not url:
        write_signin_diagnostic(step='probe', error='missing sign-in URL')
        return False, '\n'.join(lines + ['FAIL: sign-in URL not configured'])
    try:
        r = requests.get(url, timeout=timeout_sec)
        lines.append(f'GET_http={r.status_code}')
        try:
            body = r.json()
            if isinstance(body, dict):
                lines.append(f'GET_service={body.get("service", body.get("ok", ""))}')
        except Exception:
            lines.append('GET_body=non-json')
    except requests.RequestException as e:
        write_signin_diagnostic(step='probe', error=str(e))
        return False, '\n'.join(lines + [f'FAIL: {license_transient_reason(str(e))}'])
    ok_key, key_err = ensure_signin_verify_key(url)
    lines.append(f'verify_key={"ok" if _effective_public_key_b64() else "missing"}')
    if not ok_key:
        write_signin_diagnostic(step='probe', error=key_err or 'missing verify key')
        return False, '\n'.join(
            lines
            + [
                f'FAIL: {key_err or "license verify key missing in this build"}',
                'Reinstall the latest official ZubCut build.',
            ]
        )
    write_signin_diagnostic(step='probe', error='')
    return True, '\n'.join(lines + ['OK: sign-in server reachable; verify key present'])


def _signin_validate_url(base_url: str) -> str:
    base = str(base_url or '').strip()
    if not base:
        return ''
    try:
        parts = urlsplit(base)
        p = (parts.path or '/').rstrip('/')
        if not p:
            p = '/'
        if p == '/validate':
            vp = p
        else:
            vp = f'{p}/validate' if p != '/' else '/validate'
        return urlunsplit((parts.scheme, parts.netloc, vp, '', ''))
    except Exception:
        return f'{base.rstrip("/")}/validate'


def validate_active_license_session(
    url: str,
    account: str,
    license_id: str,
    *,
    timeout_sec: float = 15.0,
) -> tuple[bool | None, str]:
    """
    Check whether the current signed-in account/license is still valid.

    Returns:
      - (True, '')           => server confirms active/valid
      - (False, '<reason>')  => server explicitly invalidated access (expired/revoked/etc.)
      - (None, '<reason>')   => transient/transport issue; caller may retry later
    """
    vurl = _signin_validate_url(url)
    if not vurl:
        return None, 'Sign-in URL is not configured.'
    acct = str(account or '').strip().lower()
    lid = str(license_id or '').strip()
    if not acct:
        return False, 'Saved license is missing account identity.'
    try:
        r = requests.post(
            vurl,
            json={'account': acct, 'license_id': lid},
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            timeout=timeout_sec,
        )
    except requests.RequestException as e:
        return None, license_transient_reason(str(e))

    try:
        body = r.json()
    except Exception:
        return None, f'License server returned unexpected response (HTTP {r.status_code}).'

    if not isinstance(body, dict):
        return None, 'License server returned an unexpected response.'
    if body.get('ok'):
        return True, ''
    err = str(body.get('error') or body.get('message') or '').strip() or 'License check failed.'
    # Backward compatibility: older deployed Workers don't implement POST /validate,
    # and currently fall through to sign-in which returns 401 "Invalid credentials."
    # for our validate payload (no password). Treat this as a transient/unavailable
    # validation endpoint instead of hard-invalidating the local session.
    if r.status_code == 401 and err.casefold() in ('invalid credentials.', 'invalid credentials'):
        return None, 'Server validation endpoint unavailable (deploy latest Worker).'
    if r.status_code in (400, 401, 403, 404):
        return False, err
    return None, err
