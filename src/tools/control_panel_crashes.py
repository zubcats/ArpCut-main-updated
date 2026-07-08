"""Control Panel → Cloudflare Worker crash report admin API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from tools.license_cloud_sync import load_cloud_sync_settings

DEFAULT_TIMEOUT_SEC = 30


class CrashApiError(RuntimeError):
    pass


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_cloud_sync_settings()
    base = str(settings.get('worker_base_url') or '').strip().rstrip('/')
    secret = str(settings.get('admin_secret') or '')
    if not base.startswith('https://'):
        raise CrashApiError('Set Worker base URL (Cloud sign-in sync) and save settings.')
    if not secret:
        raise CrashApiError('Set admin secret and save settings.')
    body = json.dumps({**payload, 'secret': secret}).encode('utf-8')
    req = urllib.request.Request(
        f'{base}{path}',
        data=body,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SEC) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode('utf-8', errors='replace')
            data = json.loads(err_body) if err_body else {}
            msg = data.get('error') or err_body or str(exc)
        except Exception:
            msg = str(exc)
        raise CrashApiError(f'HTTP {exc.code}: {msg}') from exc
    except Exception as exc:
        raise CrashApiError(str(exc)) from exc


def list_crash_reports(*, limit: int = 200) -> list[dict[str, Any]]:
    data = _post('/admin/crashes/list', {'limit': max(1, min(int(limit), 500))})
    if not data.get('ok'):
        raise CrashApiError(str(data.get('error') or 'List failed'))
    rows = data.get('crashes')
    return rows if isinstance(rows, list) else []


def get_crash_report(ref: str) -> dict[str, Any]:
    data = _post('/admin/crash/get', {'ref': ref})
    if not data.get('ok'):
        raise CrashApiError(str(data.get('error') or 'Get failed'))
    report = data.get('report')
    return report if isinstance(report, dict) else {}


def delete_crash_report(ref: str) -> None:
    data = _post('/admin/crash/delete', {'ref': ref})
    if not data.get('ok'):
        raise CrashApiError(str(data.get('error') or 'Delete failed'))
