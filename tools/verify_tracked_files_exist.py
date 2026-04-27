#!/usr/bin/env python3
"""
Fail if any file recorded in Git's index is missing from the working tree.

Use this locally after sync/IDE issues, and in CI so accidental deletes break the build.

Keeping important paths *committed* is the main way to prevent silent loss; repos under
OneDrive/iCloud can still drop or conflict-copy files—prefer cloning outside sync folders.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"verify_tracked_files_exist: git ls-files failed: {e}", file=sys.stderr)
        return 2

    missing: list[str] = []
    for rel in out.split(b"\0"):
        if not rel:
            continue
        path = root / rel.decode("utf-8", errors="replace")
        if not path.is_file():
            missing.append(rel.decode("utf-8", errors="replace"))

    if missing:
        print(
            "Tracked files missing on disk (restore from git or fix sync):",
            file=sys.stderr,
        )
        for m in sorted(missing):
            print(f"  {m}", file=sys.stderr)
        return 1

    n = len([x for x in out.split(b"\0") if x])
    print(f"OK: all {n} tracked files present on disk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
