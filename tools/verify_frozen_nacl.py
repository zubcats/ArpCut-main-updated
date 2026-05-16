#!/usr/bin/env python3
"""CI smoke test: PyNaCl / libsodium must be present in the frozen onedir bundle."""

from __future__ import annotations

import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_NAME = 'ZubCut'


def main() -> int:
    root = os.path.join(_ROOT, 'dist', _APP_NAME)
    if not os.path.isdir(root):
        print(f'ERROR: dist folder missing: {root}', file=sys.stderr)
        return 1

    hits = []
    for pattern in ('**/*sodium*', '**/nacl/**', '**/_sodium*'):
        hits.extend(glob.glob(os.path.join(root, pattern), recursive=True))

    if not hits:
        print(f'ERROR: no PyNaCl/libsodium files under {root}', file=sys.stderr)
        return 1

    print(f'PyNaCl bundle check OK ({len(hits)} files), e.g. {hits[0]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
