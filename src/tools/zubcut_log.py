"""Structured append-only app log for experimental diagnostics (impairment / support)."""

from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from constants import APP_BUNDLE_NAME, DOCUMENTS_PATH, UPDATE_CHANNEL

_lock = threading.Lock()
_fp = None
_enabled: Optional[bool] = None
_MAX_LOG_BYTES = 5 * 1024 * 1024


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


def _rotate_if_needed(path: str) -> None:
    """Keep a single ``.1`` backup when the app log grows past 5 MiB."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) < _MAX_LOG_BYTES:
            return
        bak = path + '.1'
        try:
            if os.path.isfile(bak):
                os.remove(bak)
        except OSError:
            pass
        os.replace(path, bak)
    except OSError:
        pass


def _ensure_fp():
    global _fp
    if _fp is not None:
        return _fp
    if not logging_enabled():
        return None
    try:
        os.makedirs(DOCUMENTS_PATH, exist_ok=True)
        path = app_log_path()
        _rotate_if_needed(path)
        _fp = open(path, 'a', encoding='utf-8', buffering=1)
    except OSError:
        _fp = None
    return _fp


def app_log(event: str, *args: Any, exc_info: bool = False, **fields: Any) -> None:
    """Append one structured line. Never raises."""
    global _fp
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
        tb = ''
        if exc_info and sys.exc_info()[0] is not None:
            tb = traceback.format_exc()
        with _lock:
            fp = _ensure_fp()
            if fp is None:
                return
            try:
                # Mid-session rotate — startup-only rotation misses long runs.
                if fp.tell() >= _MAX_LOG_BYTES:
                    try:
                        fp.close()
                    except Exception:
                        pass
                    _fp = None
                    path = app_log_path()
                    _rotate_if_needed(path)
                    fp = _ensure_fp()
                    if fp is None:
                        return
            except Exception:
                pass
            fp.write(line)
            if tb:
                fp.write(tb)
                if not tb.endswith('\n'):
                    fp.write('\n')
            fp.flush()
    except Exception:
        pass
