"""
Uncaught Python errors: assign a short reference code, save details under %TEMP%,
and show a simple dialog so users can report the code (and attach the log).

Native hard crashes (access violations, etc.) cannot run Python afterward, so no
popup is possible there; faulthandler / OS error reporting still applies.

After the dialog, the process exits with code 1. PyQt otherwise tends to keep
running after excepthook returns for errors raised from Qt slots/timers.

While the crash dialog is open, the nested event loop can still run timers; a
second uncaught error only triggers an immediate exit (no extra dialogs).
"""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timezone

from constants import APP_BUNDLE_NAME

_ALPHABET = '0123456789ABCDEFGHJKLMNPQRSTUVWXYZ'  # skip I, O

_prev_sys_excepthook = None
_prev_threading_excepthook = None
_installed = False
# QMessageBox.exec_() runs a nested event loop; timers/slots can re-enter excepthook.
_handling_main_thread_crash = False


def _make_crash_ref() -> str:
    n = secrets.randbelow(len(_ALPHABET) ** 6)
    chars = []
    for _ in range(6):
        chars.append(_ALPHABET[n % len(_ALPHABET)])
        n //= len(_ALPHABET)
    return 'ZC-' + ''.join(reversed(chars))


def _crash_log_path(ref: str) -> str:
    return os.path.join(tempfile.gettempdir(), f'{APP_BUNDLE_NAME}-crash-{ref}.log')


def _write_report(ref: str, body: str) -> str:
    path = _crash_log_path(ref)
    head = [
        f'reference={ref}',
        f'time_utc={datetime.now(timezone.utc).isoformat()}',
        f'platform={sys.platform}',
        f'frozen={getattr(sys, "frozen", False)}',
        f'executable={sys.executable!r}',
        f'python={sys.version.splitlines()[0]!r}',
        '',
    ]
    with open(path, 'w', encoding='utf-8', errors='replace') as fp:
        fp.write('\n'.join(head))
        fp.write(body)
        if not body.endswith('\n'):
            fp.write('\n')
    return path


def _native_message_box(title: str, text: str) -> None:
    if not sys.platform.startswith('win'):
        try:
            print(text, file=sys.stderr)
        except Exception:
            pass
        return
    try:
        import ctypes

        MB_OK = 0x00000000
        MB_ICONERROR = 0x00000010
        MB_TOPMOST = 0x00040000
        ctypes.windll.user32.MessageBoxW(None, text, title, MB_OK | MB_ICONERROR | MB_TOPMOST)
    except Exception:
        try:
            print(text, file=sys.stderr)
        except Exception:
            pass


def _show_main_thread_dialog(ref: str, path: str) -> None:
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        if app is None:
            raise RuntimeError('no QApplication')
        msg = (
            'The app hit an unexpected error.\n\n'
            f'Error code (include this in your report):\n{ref}\n\n'
            f'Technical details were saved to:\n{path}\n\n'
            'The app will close when you click OK.'
        )
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(f'{APP_BUNDLE_NAME} — unexpected error')
        box.setText(msg)
        box.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        box.exec_()
    except Exception:
        _native_message_box(
            f'{APP_BUNDLE_NAME} error',
            f'Code: {ref}\n\nDetails file:\n{path}',
        )


def _our_sys_excepthook(exc_type, exc, tb) -> None:
    global _handling_main_thread_crash
    if _handling_main_thread_crash:
        try:
            sys.stderr.write(
                f'{APP_BUNDLE_NAME}: another uncaught error while the crash dialog was open; exiting.\n'
            )
            sys.stderr.write(''.join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        os._exit(1)
    _handling_main_thread_crash = True

    ref = _make_crash_ref()
    body = ''.join(traceback.format_exception(exc_type, exc, tb))
    try:
        path = _write_report(ref, body)
    except Exception:
        path = '(could not write log file)'
    try:
        _show_main_thread_dialog(ref, path)
    except Exception:
        pass
    if _prev_sys_excepthook is not None:
        try:
            _prev_sys_excepthook(exc_type, exc, tb)
        except Exception:
            pass
    else:
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    # Qt often calls excepthook for errors in slots/timers then returns to the event loop,
    # so the process would keep running unless we exit explicitly.
    if not issubclass(exc_type, (SystemExit, KeyboardInterrupt)):
        try:
            from PyQt5.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.quit()
        except Exception:
            pass
        os._exit(1)


def _our_threading_excepthook(args) -> None:
    ref = _make_crash_ref()
    tname = getattr(args.thread, 'name', '?')
    header = f'=== uncaught in thread {tname!r} ===\n'
    body = header + ''.join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    )
    try:
        path = _write_report(ref, body)
    except Exception:
        path = '(could not write log file)'
    _native_message_box(
        f'{APP_BUNDLE_NAME} error (background thread)',
        f'Code: {ref}\n\nDetails file:\n{path}',
    )
    if _prev_threading_excepthook is not None:
        _prev_threading_excepthook(args)


def install_crash_feedback() -> None:
    """Call once after QApplication exists. Chains with other hooks (e.g. updater debug)."""
    global _installed, _prev_sys_excepthook, _prev_threading_excepthook
    if _installed:
        return
    _installed = True
    _prev_sys_excepthook = sys.excepthook
    sys.excepthook = _our_sys_excepthook
    if hasattr(threading, 'excepthook'):
        _prev_threading_excepthook = threading.excepthook
        threading.excepthook = _our_threading_excepthook
