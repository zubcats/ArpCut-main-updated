#!/usr/bin/env python3
"""Write output/build-info.json from CI-stamped src/constants.py."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def _grab_assign(text: str, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\s*=\s*(.+)$", text, re.M)
    if not m:
        return ""
    raw = m.group(1).strip()
    if (raw.startswith("'") and raw.endswith("'")) or (
        raw.startswith('"') and raw.endswith('"')
    ):
        return raw[1:-1]
    return raw.strip("'\"")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", required=True)
    args = parser.parse_args()

    constants = Path("src/constants.py")
    if not constants.is_file():
        print("ERROR: src/constants.py not found", file=sys.stderr)
        sys.exit(1)

    text = constants.read_text(encoding="utf-8")
    built_at = _grab_assign(text, "APP_BUILD_TIME_ISO")
    commit = _grab_assign(text, "APP_BUILD_COMMIT") or os.environ.get("GITHUB_SHA", "").strip()
    manifest = {
        "commit": commit,
        "built_at": built_at,
        "channel": str(args.channel).strip(),
    }
    out = Path("output/build-info.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, separators=(",", ":")) + "\n", encoding="utf-8")
    print("Wrote build-info.json", manifest)


if __name__ == "__main__":
    main()
