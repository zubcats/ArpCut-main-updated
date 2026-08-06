#!/usr/bin/env python3
"""CI/local: refuse to ship a PyInstaller onedir missing the Python runtime DLL."""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# PyInstaller 6 onedir layout used by build.py / build_control_panel.py
_DEFAULTS = (
    ('ZubCut', 'python311.dll'),
    ('ZubCutControlPanel', 'python311.dll'),
)


def verify_onedir(dist_dir: str, *, dll_name: str = 'python311.dll') -> list[str]:
    """Return a list of error strings (empty means OK)."""
    errors: list[str] = []
    exe_name = os.path.basename(os.path.normpath(dist_dir)) + '.exe'
    exe_path = os.path.join(dist_dir, exe_name)
    internal = os.path.join(dist_dir, '_internal')
    dll_path = os.path.join(internal, dll_name)

    if not os.path.isdir(dist_dir):
        errors.append(f'missing onedir folder: {dist_dir}')
        return errors
    if not os.path.isfile(exe_path):
        errors.append(f'missing launcher exe: {exe_path}')
    if not os.path.isdir(internal):
        errors.append(f'missing _internal folder: {internal}')
        return errors
    if not os.path.isfile(dll_path):
        errors.append(f'missing Python runtime DLL: {dll_path}')
    elif os.path.getsize(dll_path) < 100_000:
        errors.append(f'Python runtime DLL looks truncated: {dll_path}')
    return errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        '--dist-dir',
        action='append',
        default=[],
        help='Onedir folder under dist/ (repeatable). Default: ZubCut if present.',
    )
    p.add_argument('--dll-name', default='python311.dll')
    args = p.parse_args(argv)

    targets = list(args.dist_dir)
    if not targets:
        for name, _dll in _DEFAULTS:
            candidate = os.path.join(_ROOT, 'dist', name)
            if os.path.isdir(candidate):
                targets.append(candidate)
    if not targets:
        print('verify_onedir_payload: no dist onedir found', file=sys.stderr)
        return 2

    all_errors: list[str] = []
    for dist_dir in targets:
        abs_dir = dist_dir if os.path.isabs(dist_dir) else os.path.join(_ROOT, dist_dir)
        # Allow bare names like ZubCut
        if not os.path.isdir(abs_dir) and not os.path.isabs(dist_dir):
            abs_dir = os.path.join(_ROOT, 'dist', dist_dir)
        errs = verify_onedir(abs_dir, dll_name=args.dll_name)
        if errs:
            all_errors.extend(errs)
        else:
            print(f'OK {abs_dir} (_internal/{args.dll_name})')

    if all_errors:
        for e in all_errors:
            print(f'ERROR: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
