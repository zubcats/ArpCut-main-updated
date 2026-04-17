"""
Diagnostics for the in-app updater: append-only log, uncaught exception hooks,
Qt message handler, and faulthandler (best-effort for hard crashes).

Log path: %TEMP%/<APP_BUNDLE_NAME>-updater-debug.log
Enable always when an update flow runs; set env ZUBCUT_UPDATER_DEBUG=1 to log extra detail.
"""

from __future__ import annotations

import faulthandler
import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timezone

from constants import APP_BUNDLE_NAME

_log_lock = threading.Lock()
_log_fp = None
_session_started = False
_prev_excepthook = None
_prev_threading_excepthook = None
_verbose = False


def updater_debug_log_path() -> str:
    return os.path.join(tempfile.gettempdir(), f'{APP_BUNDLE_NAME}-updater-debug.log')


def _want_verbose() -> bool:
    return os.environ.get('ZUBCUT_UPDATER_DEBUG', '').strip() in ('1', 'true', 'yes', 'on')


def updater_log(fmt: str, *args, exc_info: bool = False) -> None:
    """Thread-safe line to the updater debug log (and stderr if verbose)."""
    global _log_fp
    try:
        line = fmt % args if args else fmt
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        buf = f'{ts} {line}\n'
        if exc_info:
            buf += ''.join(traceback.format_exc())
        with _log_lock:
            if _log_fp is not None:
                _log_fp.write(buf)
                _log_fp.flush()
        if _verbose:
            sys.stderr.write(buf)
            sys.stderr.flush()
    except Exception:
        pass


def _qt_message_handler(mode, context, message):
    try:
        loc = ''
        if context is not None and getattr(context, 'file', None):
            loc = f'{context.file}:{getattr(context, "line", 0)} '
        updater_log('Qt msg type=%s %s%s', int(mode), loc, message)
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    try:
        with _log_lock:
            if _log_fp is not None:
                _log_fp.write('=== UNCAUGHT (main thread) ===\n')
                traceback.print_exception(exc_type, exc, tb, file=_log_fp)
                _log_fp.flush()
    except Exception:
        pass
    if _prev_excepthook is not None:
        _prev_excepthook(exc_type, exc, tb)
    else:
        sys.__excepthook__(exc_type, exc, tb)


def _threading_excepthook(args):
    try:
        with _log_lock:
            if _log_fp is not None:
                _log_fp.write(
                    f'=== UNCAUGHT (thread {getattr(args.thread, "name", "?")!r}) ===\n'
                )
                traceback.print_exception(
                    args.exc_type, args.exc_value, args.exc_traceback, file=_log_fp
                )
                _log_fp.flush()
    except Exception:
        pass
    if _prev_threading_excepthook is not None:
        _prev_threading_excepthook(args)


def begin_updater_debug_session(reason: str) -> None:
    """
    Idempotent. Call when entering any updater UI/download path (QApplication must exist
    before Qt message handler is useful; hooks are safe earlier).
    """
    global _log_fp, _session_started, _prev_excepthook, _prev_threading_excepthook, _verbose

    _verbose = _want_verbose()

    with _log_lock:
        if _session_started:
            try:
                if _log_fp is not None:
                    _log_fp.write(
                        f'{datetime.now(timezone.utc).isoformat()} re-enter: {reason}\n'
                    )
                    _log_fp.flush()
            except Exception:
                pass
            return

        path = updater_debug_log_path()
        try:
            _log_fp = open(path, 'a', encoding='utf-8', buffering=1)
        except OSError as e:
            sys.stderr.write(f'ZubCut updater debug: could not open {path}: {e}\n')
            return

        _session_started = True
        frozen = getattr(sys, 'frozen', False)
        exe = getattr(sys, 'executable', '')
        _log_fp.write(
            '\n'
            f'======== ZubCut updater session: {reason} ========\n'
            f'time(utc)={datetime.now(timezone.utc).isoformat()}\n'
            f'pid={os.getpid()}\n'
            f'frozen={frozen}\n'
            f'executable={exe}\n'
            f'python={sys.version}\n'
            f'log_file={path}\n'
            f'cwd={os.getcwd()}\n'
        )
        _log_fp.flush()

        try:
            faulthandler.enable(_log_fp)
        except Exception as e:
            _log_fp.write(f'faulthandler.enable failed: {e}\n')
            _log_fp.flush()

        _prev_excepthook = sys.excepthook
        sys.excepthook = _excepthook

        if hasattr(threading, 'excepthook'):
            try:
                _prev_threading_excepthook = threading.excepthook
                threading.excepthook = _threading_excepthook
            except Exception as e:
                _log_fp.write(f'threading.excepthook install failed: {e}\n')
                _log_fp.flush()

        try:
            from PyQt5.QtCore import qInstallMessageHandler

            qInstallMessageHandler(_qt_message_handler)
            _log_fp.write('Qt qInstallMessageHandler installed\n')
            _log_fp.flush()
        except Exception as e:
            _log_fp.write(f'Qt message handler install failed: {e}\n')
            _log_fp.flush()

