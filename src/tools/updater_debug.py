"""
Diagnostics for the in-app updater: append-only log, uncaught exception hooks,
Qt message handler, and faulthandler (best-effort for hard crashes).

Primary log: %TEMP%/<APP_BUNDLE_NAME>-updater-debug.log

When a git repo root is found (from cwd or the exe directory), the same lines are
mirrored to <repo>/ZubCut-updater-debug.log so a Cursor workspace on that clone
can open the file after a crash. Override with env ZUBCUT_CRASHLOG_DIR (absolute
folder path).

Set ZUBCUT_UPDATER_DEBUG=1 to also mirror lines to stderr.
"""

from __future__ import annotations

import faulthandler
import io
import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timezone

from constants import APP_BUNDLE_NAME

_log_lock = threading.Lock()
_log_fps: list = []
_session_started = False
_prev_excepthook = None
_prev_threading_excepthook = None
_verbose = False


def updater_debug_log_path() -> str:
    """Primary (temp) log — always writable."""
    return os.path.join(tempfile.gettempdir(), f'{APP_BUNDLE_NAME}-updater-debug.log')


def workspace_mirror_log_path() -> str | None:
    """
    Path of the repo/workspace mirror file if this session opened one.
    Cursor can read this path when the repo folder is the project root.
    """
    with _log_lock:
        if len(_log_fps) > 1:
            try:
                return os.path.abspath(_log_fps[1].name)
            except Exception:
                return None
    return None


def _mirror_dir_candidates() -> str | None:
    env = (os.environ.get('ZUBCUT_CRASHLOG_DIR') or '').strip()
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    return _find_git_root(
        [
            os.getcwd(),
            os.path.dirname(sys.executable),
        ]
    )


def _find_git_root(paths: list) -> str | None:
    for base in paths:
        if not base:
            continue
        p = os.path.abspath(base)
        for _ in range(10):
            if os.path.isdir(os.path.join(p, '.git')):
                return p
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    return None


def _want_verbose() -> bool:
    return os.environ.get('ZUBCUT_UPDATER_DEBUG', '').strip() in ('1', 'true', 'yes', 'on')


def _write_all(buf: str) -> None:
    with _log_lock:
        for fp in _log_fps:
            try:
                fp.write(buf)
                fp.flush()
            except Exception:
                pass
    if _verbose:
        try:
            sys.stderr.write(buf)
            sys.stderr.flush()
        except Exception:
            pass


def updater_log(fmt: str, *args, exc_info: bool = False) -> None:
    """Thread-safe line to all log targets (temp + workspace mirror)."""
    try:
        line = fmt % args if args else fmt
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        buf = f'{ts} {line}\n'
        if exc_info:
            buf += ''.join(traceback.format_exc())
        _write_all(buf)
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
        sio = io.StringIO()
        sio.write('=== UNCAUGHT (main thread) ===\n')
        traceback.print_exception(exc_type, exc, tb, file=sio)
        _write_all(sio.getvalue())
    except Exception:
        pass
    if _prev_excepthook is not None:
        _prev_excepthook(exc_type, exc, tb)
    else:
        sys.__excepthook__(exc_type, exc, tb)


def _threading_excepthook(args):
    try:
        sio = io.StringIO()
        sio.write(f'=== UNCAUGHT (thread {getattr(args.thread, "name", "?")!r}) ===\n')
        traceback.print_exception(
            args.exc_type, args.exc_value, args.exc_traceback, file=sio
        )
        _write_all(sio.getvalue())
    except Exception:
        pass
    if _prev_threading_excepthook is not None:
        _prev_threading_excepthook(args)


def begin_updater_debug_session(reason: str) -> None:
    """
    Idempotent. Call when entering any updater UI/download path (QApplication must exist
    before Qt message handler is useful; hooks are safe earlier).
    """
    global _log_fps, _session_started, _prev_excepthook, _prev_threading_excepthook, _verbose

    _verbose = _want_verbose()

    with _log_lock:
        if _session_started:
            try:
                line = f'{datetime.now(timezone.utc).isoformat()} re-enter: {reason}\n'
                for fp in _log_fps:
                    fp.write(line)
                    fp.flush()
            except Exception:
                pass
            return

        _log_fps = []
        path = updater_debug_log_path()
        try:
            _log_fps.append(open(path, 'a', encoding='utf-8', buffering=1))
        except OSError as e:
            sys.stderr.write(f'ZubCut updater debug: could not open {path}: {e}\n')
            return

        mirror_note = '(none)'
        mirror_dir = _mirror_dir_candidates()
        if mirror_dir:
            mirror_path = os.path.join(mirror_dir, f'{APP_BUNDLE_NAME}-updater-debug.log')
            try:
                _log_fps.append(
                    open(mirror_path, 'a', encoding='utf-8', buffering=1)
                )
                mirror_note = mirror_path
            except OSError as e:
                mirror_note = f'(failed {mirror_path}: {e})'

        fp0 = _log_fps[0]
        frozen = getattr(sys, 'frozen', False)
        exe = getattr(sys, 'executable', '')
        fp0.write(
            '\n'
            f'======== ZubCut updater session: {reason} ========\n'
            f'time(utc)={datetime.now(timezone.utc).isoformat()}\n'
            f'pid={os.getpid()}\n'
            f'frozen={frozen}\n'
            f'executable={exe}\n'
            f'python={sys.version}\n'
            f'log_file={path}\n'
            f'mirror_log_file={mirror_note}\n'
            f'cwd={os.getcwd()}\n'
        )
        fp0.flush()
        if len(_log_fps) > 1:
            try:
                _log_fps[1].write(
                    '\n'
                    f'======== ZubCut updater session: {reason} ========\n'
                    f'(same session as temp log; see primary for full header)\n'
                )
                _log_fps[1].flush()
            except Exception:
                pass

        _session_started = True

        try:
            faulthandler.enable(fp0)
        except Exception as e:
            fp0.write(f'faulthandler.enable failed: {e}\n')
            fp0.flush()

        _prev_excepthook = sys.excepthook
        sys.excepthook = _excepthook

        if hasattr(threading, 'excepthook'):
            try:
                _prev_threading_excepthook = threading.excepthook
                threading.excepthook = _threading_excepthook
            except Exception as e:
                fp0.write(f'threading.excepthook install failed: {e}\n')
                fp0.flush()

        try:
            from PyQt5.QtCore import qInstallMessageHandler

            qInstallMessageHandler(_qt_message_handler)
            fp0.write('Qt qInstallMessageHandler installed\n')
            fp0.flush()
        except Exception as e:
            fp0.write(f'Qt message handler install failed: {e}\n')
            fp0.flush()


def updater_log_paths_hint() -> str:
    """Human-readable paths for error dialogs (temp + workspace mirror if any)."""
    lines = [updater_debug_log_path()]
    w = workspace_mirror_log_path()
    if w:
        lines.append(w)
    return '\n'.join(lines)
