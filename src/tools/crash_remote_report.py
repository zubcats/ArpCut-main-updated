"""Upload ZubCut crash logs to the license worker for admin / Control Panel review."""

from __future__ import annotations

import json
import os
import platform
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from constants import (
    APP_BUILD_COMMIT,
    APP_BUILD_TIME_ISO,
    CRASH_INGEST_TOKEN,
    CRASH_REPORT_URL,
    LICENSE_FILE_PATH,
    SETTINGS_KEYS,
    UPDATE_CHANNEL,
)
from tools.utils_gui import import_settings_as_dict

DEFAULT_TIMEOUT_SEC = 20


def _crash_report_url() -> str:
    return (
        os.environ.get('ZUBCUT_CRASH_REPORT_URL')
        or os.environ.get('ZUBCUT_LICENSE_SIGNIN_URL')
        or os.environ.get('ZUBCUT_PAID_SIGNIN_URL')
        or CRASH_REPORT_URL
        or ''
    ).strip().rstrip('/')


def _default_headers() -> Dict[str, str]:
    return {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'ZubCut-CrashReport/1.0',
    }


def _post_json(
    url: str,
    payload: Dict[str, Any],
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers=_default_headers(), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {'raw': raw}
            return True, 'ok', data
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode('utf-8', errors='replace')
            err_data = json.loads(err_body) if err_body else {}
            msg = err_data.get('error') or err_body or str(exc)
        except Exception:
            msg = str(exc)
        return False, msg, None
    except Exception as exc:
        return False, str(exc), None


def _app_version() -> str:
    try:
        from version import __version__

        return str(__version__)
    except Exception:
        return 'unknown'


def _account_hint() -> str:
    account, _ = _license_identity()
    return account


def _license_identity() -> Tuple[str, str]:
    """Return (sign-in account key, license_id) from the installed license file."""
    try:
        from tools.license_offline import resolve_license_account

        if not LICENSE_FILE_PATH or not os.path.isfile(LICENSE_FILE_PATH):
            return '', ''
        with open(LICENSE_FILE_PATH, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        account = resolve_license_account(data)
        payload = data.get('payload') if isinstance(data, dict) else None
        license_id = ''
        if isinstance(payload, dict):
            license_id = str(payload.get('license_id') or '').strip()
        return account, license_id
    except Exception:
        return '', ''


def _parse_exception(log_text: str) -> Tuple[str, str]:
    for line in reversed((log_text or '').strip().splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith('File '):
            continue
        if ':' in stripped:
            name, _, msg = stripped.partition(':')
            name = name.strip()
            if name and name[0].isalpha() and ' ' not in name:
                return name, msg.strip()[:500]
    return '', ''


def _build_payload(
    ref: str,
    log_text: str,
    *,
    exc_type: str = '',
    exc_message: str = '',
    account_hint: str = '',
    license_id: str = '',
) -> Dict[str, Any]:
    parsed_type, parsed_msg = _parse_exception(log_text)
    account, lic_id = _license_identity()
    if account_hint:
        account = account_hint.strip().lower()[:120]
    if license_id:
        lic_id = license_id.strip()[:80]
    payload = {
        'ref': ref,
        'body': log_text,
        'time_utc': datetime.now(timezone.utc).isoformat(),
        'platform': platform.platform(),
        'frozen': bool(getattr(sys, 'frozen', False)),
        'build_commit': str(APP_BUILD_COMMIT or '')[:40],
        'build_channel': str(UPDATE_CHANNEL or ''),
        'build_time': str(APP_BUILD_TIME_ISO or ''),
        'app_version': _app_version(),
        'python': sys.version.split()[0] if sys.version else '',
        'account_hint': account,
        'license_id': lic_id[:80],
        'exc_type': (exc_type or parsed_type)[:120],
        'exc_message': (exc_message or parsed_msg)[:500],
    }
    # Diagnostic ZC-* support codes (readiness / format_error_code), not the crash ref.
    try:
        from tools.user_errors import (
            latest_zc_codes,
            parse_zc_codes_header,
            zc_code_catalog,
        )

        codes = latest_zc_codes()
        if not codes:
            codes = parse_zc_codes_header(log_text)
        # Cap payload size; catalog is small (~20 entries).
        payload['zc_codes'] = [
            {
                'code': str(c.get('code') or '')[:40],
                'level': str(c.get('level') or '')[:12],
                'source': str(c.get('source') or '')[:40],
                'message': str(c.get('message') or '')[:240],
            }
            for c in (codes or [])[:32]
            if c.get('code')
        ]
        payload['zc_catalog'] = [
            {'code': str(c.get('code') or '')[:40], 'message': str(c.get('message') or '')[:240]}
            for c in zc_code_catalog()
        ]
    except Exception:
        payload['zc_codes'] = []
        payload['zc_catalog'] = []
    # Optional worker secret (wrangler CRASH_INGEST_TOKEN). Empty = worker accepts all.
    token = (
        os.environ.get('ZUBCUT_CRASH_INGEST_TOKEN')
        or os.environ.get('CRASH_INGEST_TOKEN')
        or str(CRASH_INGEST_TOKEN or '')
    ).strip()
    if token:
        payload['ingest_token'] = token
    return payload


def submit_crash_report(
    ref: str,
    log_text: str,
    *,
    url: Optional[str] = None,
    exc_type: str = '',
    exc_message: str = '',
    account_hint: str = '',
) -> Tuple[bool, str]:
    """POST a crash report. Returns (ok, message)."""
    base = (url or _crash_report_url()).strip().rstrip('/')
    if not base:
        return False, 'Crash report URL is not configured'
    target = f'{base}/crash'
    payload = _build_payload(
        ref,
        log_text,
        exc_type=exc_type,
        exc_message=exc_message,
        account_hint=account_hint,
    )
    ok, msg, data = _post_json(target, payload)
    if ok and isinstance(data, dict) and data.get('ok'):
        return True, str(data.get('message') or 'Report sent')
    if ok:
        return True, msg
    return False, msg


def crash_auto_send_enabled() -> bool:
    settings = import_settings_as_dict()
    return bool(settings.get('crash_report_auto_send', False))


def pending_crash_path() -> str:
    base = os.environ.get('TEMP') or os.environ.get('TMP') or '.'
    return os.path.join(base, 'ZubCut-crash-pending.json')


_PENDING_CRASH_MAX = 5


def save_pending_crash(ref: str, log_path: str) -> None:
    """Remember a crash the user chose to send later (or retry on next launch).

    Keeps a bounded FIFO queue so a later crash does not erase an earlier unsent
    report (previous behavior overwrote a single pointer).
    """
    try:
        items: list = []
        path = pending_crash_path()
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and data.get('ref') and data.get('logPath'):
                    items = [data]
                elif isinstance(data, dict) and isinstance(data.get('items'), list):
                    items = [x for x in data['items'] if isinstance(x, dict)]
                elif isinstance(data, list):
                    items = [x for x in data if isinstance(x, dict)]
            except Exception:
                items = []
        items.append({'ref': ref, 'logPath': log_path})
        # Dedupe by ref, keep newest last, bound length.
        seen = set()
        deduped = []
        for item in reversed(items):
            r = str(item.get('ref') or '')
            if not r or r in seen:
                continue
            seen.add(r)
            deduped.append(item)
            if len(deduped) >= _PENDING_CRASH_MAX:
                break
        deduped.reverse()
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'items': deduped}, fh)
    except Exception:
        pass


def load_pending_crash() -> Optional[Dict[str, str]]:
    """Return the oldest pending crash (FIFO), or None."""
    path = pending_crash_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get('ref') and data.get('logPath'):
            return {'ref': str(data['ref']), 'logPath': str(data['logPath'])}
        items = []
        if isinstance(data, dict) and isinstance(data.get('items'), list):
            items = data['items']
        elif isinstance(data, list):
            items = data
        for item in items:
            if isinstance(item, dict) and item.get('ref') and item.get('logPath'):
                return {'ref': str(item['ref']), 'logPath': str(item['logPath'])}
    except Exception:
        pass
    return None


def clear_pending_crash(ref: str | None = None) -> None:
    """Clear one pending crash by ref, or the whole queue when ``ref`` is None."""
    path = pending_crash_path()
    if ref is None:
        try:
            os.remove(path)
        except Exception:
            pass
        return
    try:
        if not os.path.isfile(path):
            return
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        items = []
        if isinstance(data, dict) and isinstance(data.get('items'), list):
            items = [x for x in data['items'] if isinstance(x, dict)]
        elif isinstance(data, dict) and data.get('ref'):
            items = [data]
        elif isinstance(data, list):
            items = [x for x in data if isinstance(x, dict)]
        keep = [x for x in items if str(x.get('ref') or '') != str(ref)]
        if not keep:
            os.remove(path)
        else:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump({'items': keep}, fh)
    except Exception:
        pass


def try_send_pending_crash() -> Tuple[bool, str]:
    """On startup: retry queued crash reports from prior failed uploads (oldest first)."""
    pending = load_pending_crash()
    if not pending:
        return False, 'no pending'
    log_path = pending['logPath']
    ref = pending['ref']
    if not os.path.isfile(log_path):
        clear_pending_crash(ref)
        # Try next item if any.
        return try_send_pending_crash()
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as fh:
            log_text = fh.read()
    except Exception as exc:
        return False, str(exc)
    ok, msg = submit_crash_report(ref, log_text)
    if ok:
        clear_pending_crash(ref)
        # Drain additional queued reports opportunistically.
        more = load_pending_crash()
        if more:
            try_send_pending_crash()
        return ok, msg
    # Permanent client errors must not poison the FIFO head forever.
    low = str(msg or '').lower()
    if any(
        token in low
        for token in (
            'http error 400',
            'http error 401',
            'http error 403',
            'http error 404',
            'http error 422',
            ' 400 ',
            ' 401 ',
            ' 403 ',
            ' 404 ',
            ' 422 ',
        )
    ) or low.strip().startswith(('400', '401', '403', '404', '422')):
        clear_pending_crash(ref)
        return try_send_pending_crash()
    return ok, msg
