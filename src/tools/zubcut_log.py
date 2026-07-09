"""Structured append-only app log for experimental diagnostics (impairment / support)."""

from __future__ import annotations

import os
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from constants import APP_BUNDLE_NAME, DOCUMENTS_PATH, UPDATE_CHANNEL

_lock = threading.Lock()
_fp = None
_enabled: Optional[bool] = None


def _channel_is_experimental() -> bool:
    return str(UPDATE_CHANNEL or '').strip().lower() == 'experimental'


def app_log_path() -> str:
    return os.path.join(DOCUMENTS_PATH, f'{APP_BUNDLE_NAME.lower()}.log')


def logging_enabled() -> bool:
    global _enabled
    if _enabled is not None:
        return _enabled
    env = (os.environ.get('ZUBCUT_APP_LOG') or '').strip().lower()
    if env in ('0', 'false', 'no', 'off'):
        _enabled = False
    elif env in ('1', 'true', 'yes', 'on'):
        _enabled = True
    else:
        # Default on for experimental builds; opt-in elsewhere via env.
        _enabled = _channel_is_experimental()
    return _enabled


def _ensure_fp():
    global _fp
    if _fp is not None:
        return _fp
    if not logging_enabled():
        return None
    try:
        os.makedirs(DOCUMENTS_PATH, exist_ok=True)
        _fp = open(app_log_path(), 'a', encoding='utf-8', buffering=1)
    except OSError:
        _fp = None
    return _fp


def app_log(event: str, *args: Any, exc_info: bool = False, **fields: Any) -> None:
    """Append one structured line. Never raises."""
    if not logging_enabled():
        return
    try:
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        msg = str(event or '')
        if args:
            try:
                msg = msg % args
            except Exception:
                msg = f'{msg} {" ".join(str(a) for a in args)}'
        extra = ''
        if fields:
            bits = [f'{k}={fields[k]!r}' for k in sorted(fields)]
            extra = ' ' + ' '.join(bits)
        line = f'{ts} [{UPDATE_CHANNEL}] {msg}{extra}\n'
        with _lock:
            fp = _ensure_fp()
            if fp is None:
                return
            fp.write(line)
            if exc_info:
                fp.write(traceback.format_exc())
                fp.write('\n')
            fp.flush()
    except Exception:
        pass
