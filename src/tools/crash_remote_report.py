"""Upload ZubCut crash logs to the license worker for admin / License Manager review."""

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
    return {
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


def save_pending_crash(ref: str, log_path: str) -> None:
    """Remember a crash the user chose to send later (or retry on next launch)."""
    try:
        with open(pending_crash_path(), 'w', encoding='utf-8') as fh:
            json.dump({'ref': ref, 'logPath': log_path}, fh)
    except Exception:
        pass


def load_pending_crash() -> Optional[Dict[str, str]]:
    path = pending_crash_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get('ref') and data.get('logPath'):
            return {'ref': str(data['ref']), 'logPath': str(data['logPath'])}
    except Exception:
        pass
    return None


def clear_pending_crash() -> None:
    try:
        os.remove(pending_crash_path())
    except Exception:
        pass


def try_send_pending_crash() -> Tuple[bool, str]:
    """On startup: retry a queued crash report from a prior failed upload."""
    pending = load_pending_crash()
    if not pending:
        return False, 'no pending'
    log_path = pending['logPath']
    ref = pending['ref']
    if not os.path.isfile(log_path):
        clear_pending_crash()
        return False, 'log missing'
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as fh:
            log_text = fh.read()
    except Exception as exc:
        return False, str(exc)
    ok, msg = submit_crash_report(ref, log_text)
    if ok:
        clear_pending_crash()
    return ok, msg
