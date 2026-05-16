#!/usr/bin/env python3
"""CI: verify PyNaCl inside the frozen ZubCut.exe (not system Python)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_NAME = 'ZubCut'
_REPORT = os.path.join(tempfile.gettempdir(), 'zubcut-license-crypto-verify.txt')


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

    r = subprocess.run(
        [exe, '--verify-license-crypto'],
        cwd=os.path.dirname(exe),
        capture_output=True,
        text=True,
        timeout=120,
    )
    report = ''
    if os.path.isfile(_REPORT):
        try:
            report = open(_REPORT, encoding='utf-8').read().strip()
        except OSError:
            pass
    if not report:
        report = (r.stdout or '').strip() or (r.stderr or '').strip()

    print(report or f'(no report, exit {r.returncode})')
    if r.returncode != 0:
        print('ERROR: frozen ZubCut.exe crypto self-test failed', file=sys.stderr)
        return 1
    if 'OK' not in report.splitlines()[-1:]:
        print('ERROR: crypto self-test did not report OK', file=sys.stderr)
        return 1
    print('Frozen exe PyNaCl self-test passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
