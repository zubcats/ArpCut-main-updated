"""HTTPS calls to the ZubCut license Cloudflare worker."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TIMEOUT_SEC = 30


class CloudApiError(RuntimeError):
    pass


def _post_json(url: str, payload: dict[str, Any], *, timeout: int = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode('utf-8', errors='replace')
            data = json.loads(err_body) if err_body else {}
            msg = data.get('error') or err_body or str(exc)
        except Exception:
            msg = str(exc)
        raise CloudApiError(f'HTTP {exc.code}: {msg}') from exc
    except Exception as exc:
        raise CloudApiError(str(exc)) from exc


def _base(worker_url: str) -> str:
    return str(worker_url or '').strip().rstrip('/')


def test_connection(worker_url: str, admin_secret: str) -> str:
    data = _post_json(
        f'{_base(worker_url)}/admin/crashes/list',
        {'secret': admin_secret, 'limit': 1},
    )
    if not data.get('ok'):
        raise CloudApiError(str(data.get('error') or 'Connection test failed'))
    total = data.get('total', 0)
    return f'Connected. Crash index has {total} report(s).'


def upsert_account(worker_url: str, admin_secret: str, account_key: str, bundle: dict[str, Any]) -> None:
    data = _post_json(
        f'{_base(worker_url)}/admin/upsert',
        {'secret': admin_secret, 'account_key': account_key, 'bundle': bundle},
    )
    if not data.get('ok'):
        raise CloudApiError(str(data.get('error') or 'Upsert failed'))


def delete_account(worker_url: str, admin_secret: str, account_key: str) -> None:
    data = _post_json(
        f'{_base(worker_url)}/admin/delete',
        {'secret': admin_secret, 'account_key': account_key},
    )
    if not data.get('ok'):
        raise CloudApiError(str(data.get('error') or 'Delete failed'))


def list_crashes(worker_url: str, admin_secret: str, *, limit: int = 100) -> list[dict[str, Any]]:
    data = _post_json(
        f'{_base(worker_url)}/admin/crashes/list',
        {'secret': admin_secret, 'limit': max(1, min(int(limit), 500))},
    )
    if not data.get('ok'):
        raise CloudApiError(str(data.get('error') or 'List failed'))
    rows = data.get('crashes')
    return rows if isinstance(rows, list) else []


def get_crash(worker_url: str, admin_secret: str, ref: str) -> dict[str, Any]:
    data = _post_json(
        f'{_base(worker_url)}/admin/crash/get',
        {'secret': admin_secret, 'ref': ref},
    )
    if not data.get('ok'):
        raise CloudApiError(str(data.get('error') or 'Get failed'))
    report = data.get('report')
    return report if isinstance(report, dict) else {}


def delete_crash(worker_url: str, admin_secret: str, ref: str) -> None:
    data = _post_json(
        f'{_base(worker_url)}/admin/crash/delete',
        {'secret': admin_secret, 'ref': ref},
    )
    if not data.get('ok'):
        raise CloudApiError(str(data.get('error') or 'Delete failed'))
