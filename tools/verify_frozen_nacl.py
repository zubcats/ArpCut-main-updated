#!/usr/bin/env python3
"""CI: verify license Ed25519 crypto inside frozen ZubCut.exe (not system Python)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_NAME = 'ZubCut'
_REPORT = os.path.join(tempfile.gettempdir(), 'zubcut-license-crypto-verify.txt')


def _read_report() -> str:
    if not os.path.isfile(_REPORT):
        return ''
    try:
        return open(_REPORT, encoding='utf-8').read().strip()
    except OSError:
        return ''


def _report_ok(report: str) -> bool:
    lines = [ln.strip() for ln in report.splitlines() if ln.strip()]
    return bool(lines) and lines[-1] == 'OK'


def _windows_subprocess_kwargs() -> dict:
    if os.name != 'nt':
        return {}
    kw: dict = {}
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    if no_window:
        kw['creationflags'] = no_window
    return kw


def main() -> int:
    exe = os.path.join(_ROOT, 'dist', _APP_NAME, f'{_APP_NAME}.exe')
    if not os.path.isfile(exe):
        print(f'ERROR: frozen exe not found: {exe}', file=sys.stderr)
        return 1

    try:
        if os.path.isfile(_REPORT):
            os.remove(_REPORT)
    except OSError:
        pass

    cmd = [exe, '--verify-license-crypto']
    cwd = os.path.dirname(exe)
    deadline = time.monotonic() + 45.0
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_windows_subprocess_kwargs(),
    )
    report = ''
    returncode = None
    while time.monotonic() < deadline:
        report = _read_report()
        if report and _report_ok(report):
            returncode = 0
            break
        if proc.poll() is not None:
            returncode = proc.returncode
            break
        time.sleep(0.25)

    if returncode is None:
        report = _read_report()
        if report and _report_ok(report):
            returncode = 0
        else:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            print(
                'ERROR: frozen ZubCut.exe crypto self-test timed out after 45s '
                f'(cmd={cmd!r})',
                file=sys.stderr,
            )
            if report:
                print(report)
            return 1

    stdout, stderr = '', ''
    try:
        stdout, stderr = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    if not report:
        report = (stdout or '').strip() or (stderr or '').strip()

    print(report or f'(no report, exit {returncode})')
    if returncode != 0:
        print('ERROR: frozen ZubCut.exe crypto self-test failed', file=sys.stderr)
        return 1
    if not _report_ok(report):
        print('ERROR: crypto self-test did not report OK', file=sys.stderr)
        return 1
    print('Frozen exe license crypto self-test passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
