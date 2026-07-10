#!/usr/bin/env python3
"""Copy tracked build.py / src/constants.py into .github/ci-blessed mirrors.

Use after intentional edits so unit-test drift checks stay green. Installer
workflows no longer silently overwrite tracked sources from these mirrors.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MIRROR = _ROOT / '.github' / 'ci-blessed'


def main() -> int:
    pairs = (
        (_ROOT / 'build.py', _MIRROR / 'build.py'),
        (_ROOT / 'src' / 'constants.py', _MIRROR / 'constants.py'),
    )
    _MIRROR.mkdir(parents=True, exist_ok=True)
    for src, dst in pairs:
        if not src.is_file():
            print(f'missing source: {src}', file=sys.stderr)
            return 1
        shutil.copy2(src, dst)
        print(f'updated {dst.relative_to(_ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
