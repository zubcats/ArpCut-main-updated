"""
ZubCut Control Panel → Cloudflare Worker: push account bundles so customers can sign in online.

Settings live in PAID_LICENSE_MANAGER_CLOUD_SYNC_PATH (JSON). See backend/cloudflare-license-signin/README.md.
"""
from __future__ import annotations

import json
import os
from typing import Any

import requests

from constants import PAID_LICENSE_MANAGER_CLOUD_SYNC_PATH

WORKER_HTTP_USER_AGENT = 'ZubCut-ControlPanel/1.0'


def worker_http_headers(*, json_body: bool = True) -> dict[str, str]:
    """Headers for Control Panel → Cloudflare Worker (avoids CF Error 1010 on default Python UA)."""
    headers = {'Accept': 'application/json', 'User-Agent': WORKER_HTTP_USER_AGENT}
    if json_body:
        headers['Content-Type'] = 'application/json'
    return headers


def _defaults() -> dict[str, Any]:
    return {'version': 1, 'worker_base_url': '', 'admin_secret': '', 'auto_sync': True}


def load_cloud_sync_settings() -> dict[str, Any]:
    out = _defaults()
    path = PAID_LICENSE_MANAGER_CLOUD_SYNC_PATH
    if not os.path.exists(path):
        return out
    try:
        raw = json.load(open(path, 'r', encoding='utf-8'))
    except Exception:
        return out
    if not isinstance(raw, dict):
        return out
    for k in ('worker_base_url', 'admin_secret', 'auto_sync'):
        if k in raw:
            out[k] = raw[k]
    try:
        from tools.secret_store import unprotect_secret

        out['admin_secret'] = unprotect_secret(str(out.get('admin_secret') or ''))
    except Exception:
        pass
    return out


def save_cloud_sync_settings(
    *,
    worker_base_url: str,
    admin_secret: str,
    auto_sync: bool,
) -> None:
    secret = str(admin_secret or '')
    try:
        from tools.secret_store import protect_secret, restrict_user_only_acl

        secret = protect_secret(secret)
    except Exception:
        restrict_user_only_acl = None  # type: ignore
    data = {
        'version': 1,
        'worker_base_url': str(worker_base_url or '').strip().rstrip('/'),
        'admin_secret': secret,
        'auto_sync': bool(auto_sync),
    }
    parent = os.path.dirname(PAID_LICENSE_MANAGER_CLOUD_SYNC_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(PAID_LICENSE_MANAGER_CLOUD_SYNC_PATH, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)
    try:
        from tools.secret_store import restrict_user_only_acl as _acl

        _acl(PAID_LICENSE_MANAGER_CLOUD_SYNC_PATH)
    except Exception:
        pass


def _normalize_worker_base(url: str) -> str:
    return str(url or '').strip().rstrip('/')


def format_worker_api_error(status_code: int, error_text: str) -> str:
    """Turn worker JSON errors into Control Panel guidance."""
    err = str(error_text or '').strip()
    if status_code == 401 and err == 'Invalid credentials.':
        return (
            'Worker treated this as a customer sign-in, not the crash admin API. '
            'Use the base Worker URL only (https://….workers.dev), redeploy the worker '
            'from backend/cloudflare-license-signin (npx wrangler deploy), and set Admin secret '
            'to your wrangler ADMIN_SECRET (not a customer password).'
        )
    if status_code == 401 and err == 'Unauthorized.':
        return 'Admin secret does not match the worker ADMIN_SECRET. Re-enter it on Accounts and Save.'
    if err:
        return f'HTTP {status_code}: {err}'
    return f'HTTP {status_code}'


def test_worker_reachable(worker_base_url: str) -> tuple[bool, str]:
    base = _normalize_worker_base(worker_base_url)
    if not base.startswith('https://'):
        return False, 'Worker URL must start with https://'
    try:
        r = requests.get(
            f'{base}/',
            headers=worker_http_headers(json_body=False),
            timeout=15,
        )
    except requests.RequestException as e:
        return False, str(e)
    try:
        body = r.json()
    except Exception:
        return False, f'Unexpected response (HTTP {r.status_code}).'
    if isinstance(body, dict) and body.get('ok') and body.get('service') == 'zubcut-license-signin':
        return True, 'Worker responded OK.'
    if r.status_code == 200:
        return True, 'Worker responded (HTTP 200).'
    return False, f'Worker returned HTTP {r.status_code}.'


def test_worker_admin_access(worker_base_url: str, admin_secret: str) -> tuple[bool, str]:
    """Verify crash admin API (POST /admin/crashes/list) with ADMIN_SECRET."""
    base = _normalize_worker_base(worker_base_url)
    if not base.startswith('https://'):
        return False, 'Worker URL must start with https://'
    secret = str(admin_secret or '').strip()
    if not secret:
        return False, 'Set admin secret (wrangler ADMIN_SECRET) and save settings.'
    ok_reach, reach_msg = test_worker_reachable(base)
    if not ok_reach:
        return False, reach_msg
    try:
        r = requests.post(
            f'{base}/admin/crashes/list',
            json={'secret': secret, 'limit': 1},
            headers=worker_http_headers(),
            timeout=15,
        )
    except requests.RequestException as e:
        return False, str(e)
    try:
        body = r.json()
    except Exception:
        return False, f'Unexpected response (HTTP {r.status_code}).'
    if isinstance(body, dict) and body.get('ok'):
        total = body.get('total', len(body.get('crashes') or []))
        return True, f'Admin API OK ({total} crash report(s) on worker).'
    err = str((body or {}).get('error') or '').strip() if isinstance(body, dict) else ''
    return False, format_worker_api_error(r.status_code, err)


def push_account_to_worker(license_id: str) -> tuple[bool, str]:
    """POST /admin/upsert with bundle from license_admin."""
    from tools.license_admin import cloud_kv_bundle_for_license_id, cloud_kv_key_for_account, signed_document_for_license_id

    s = load_cloud_sync_settings()
    base = _normalize_worker_base(str(s.get('worker_base_url') or ''))
    secret = str(s.get('admin_secret') or '')
    if not base.startswith('https://'):
        return False, 'Set a Worker base URL starting with https:// and save settings.'
    if not secret:
        return False, 'Set the admin secret (same as wrangler secret ADMIN_SECRET) and save settings.'

    bundle = cloud_kv_bundle_for_license_id(license_id)
    if bundle is None:
        return False, 'This account needs a customer sign-in password (online uses the same hash as ZubCut).'

    doc = bundle.get('license') or {}
    p = doc.get('payload') or {}
    key = cloud_kv_key_for_account(str(p.get('user_name') or ''))
    if not key:
        return False, 'Account name is missing from the license.'

    url = f'{base}/admin/upsert'
    try:
        r = requests.post(
            url,
            json={'secret': secret, 'account_key': key, 'bundle': bundle},
            headers=worker_http_headers(),
            timeout=45,
        )
    except requests.RequestException as e:
        return False, f'Could not reach Worker: {e}'

    try:
        body = r.json()
    except Exception:
        return False, f'Worker returned HTTP {r.status_code} (not JSON).'

    if isinstance(body, dict) and body.get('ok'):
        return True, 'Pushed to cloud.'

    err = str((body or {}).get('error') or 'Upsert failed').strip() if isinstance(body, dict) else 'Upsert failed'
    if r.status_code in (401, 403):
        return False, format_worker_api_error(r.status_code, err)
    return False, err


def delete_account_from_worker(account_key: str) -> tuple[bool, str]:
    """
    POST /admin/delete to remove the KV row for this account (lowercase user name).

    If Worker URL or admin secret is not configured, returns (True, '') and does nothing.
    """
    key = str(account_key or '').strip().casefold()
    if not key:
        return True, ''

    s = load_cloud_sync_settings()
    base = _normalize_worker_base(str(s.get('worker_base_url') or ''))
    secret = str(s.get('admin_secret') or '')
    if not base.startswith('https://') or not secret:
        return True, ''

    url = f'{base}/admin/delete'
    try:
        r = requests.post(
            url,
            json={'secret': secret, 'account_key': key},
            headers=worker_http_headers(),
            timeout=45,
        )
    except requests.RequestException as e:
        return False, f'Could not reach Worker: {e}'

    try:
        body = r.json()
    except Exception:
        return False, f'Worker returned HTTP {r.status_code} (not JSON).'

    if isinstance(body, dict) and body.get('ok'):
        return True, 'Removed from cloud.'

    err = str((body or {}).get('error') or 'Delete failed').strip() if isinstance(body, dict) else 'Delete failed'
    return False, err
