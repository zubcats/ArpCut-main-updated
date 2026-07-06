"""
License sign-in: POST account + password to a HTTPS endpoint; response includes the signed license document.

Used with the Cloudflare Worker in backend/cloudflare-license-signin/.
"""
from __future__ import annotations

import json
import os
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


def effective_signin_url() -> str:
    """HTTPS license server URL (empty if not configured)."""
    try:
        from constants import LICENSE_SIGNIN_URL
    except Exception:
        LICENSE_SIGNIN_URL = ''
    return (
        str(
            os.environ.get('ZUBCUT_LICENSE_SIGNIN_URL')
            or os.environ.get('ZUBCUT_PAID_SIGNIN_URL')
            or LICENSE_SIGNIN_URL
            or ''
        ).strip()
    )


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
    if not acct or not lid:
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
