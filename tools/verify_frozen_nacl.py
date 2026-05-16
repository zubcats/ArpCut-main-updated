#!/usr/bin/env python3
"""CI smoke test: PyNaCl must import from the frozen onedir bundle (not just exist on disk)."""

from __future__ import annotations

import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_NAME = 'ZubCut'


def _bootstrap_internal_path(internal: str) -> None:
    if internal not in sys.path:
        sys.path.insert(0, internal)
    if sys.platform.startswith('win'):
        try:
            os.add_dll_directory(internal)
        except (AttributeError, OSError):
            pass
        nacl_dir = os.path.join(internal, 'nacl')
        if os.path.isdir(nacl_dir):
            try:
                os.add_dll_directory(nacl_dir)
            except (AttributeError, OSError):
                pass


def main() -> int:
    root = os.path.join(_ROOT, 'dist', _APP_NAME)
    internal = os.path.join(root, '_internal')
    if not os.path.isdir(internal):
        print(f'ERROR: frozen _internal missing: {internal}', file=sys.stderr)
        return 1

    hits = []
    for pattern in ('**/*sodium*', '**/nacl/**', '**/_sodium*'):
        hits.extend(glob.glob(os.path.join(root, pattern), recursive=True))
    if not hits:
        print(f'ERROR: no PyNaCl/libsodium files under {root}', file=sys.stderr)
        return 1

    _bootstrap_internal_path(internal)
    try:
        from nacl.signing import VerifyKey  # noqa: F401
    except ImportError as e:
        print(f'ERROR: PyNaCl import failed from {internal}: {e}', file=sys.stderr)
        return 1
    except Exception as e:
        print(f'ERROR: PyNaCl load failed from {internal}: {e}', file=sys.stderr)
        return 1

    print(f'PyNaCl import OK ({len(hits)} bundle files), e.g. {hits[0]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
