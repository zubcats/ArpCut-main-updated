"""
Paid sign-in: POST account + password to a HTTPS endpoint; response includes the signed license document.

Used with the Cloudflare Worker in backend/cloudflare-license-signin/.
"""
from __future__ import annotations

import json
import os
from typing import Any

import requests


def effective_signin_url() -> str:
    """HTTPS license server URL (empty if not configured)."""
    try:
        from constants import PAID_LICENSE_SIGNIN_URL
    except Exception:
        PAID_LICENSE_SIGNIN_URL = ''
    return (
        str(os.environ.get('ZUBCUT_PAID_SIGNIN_URL') or PAID_LICENSE_SIGNIN_URL or '').strip()
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
    account = str(account or '').strip()
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
        return None, f'Could not reach the sign-in server ({e}).'

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
