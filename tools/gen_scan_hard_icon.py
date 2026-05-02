"""
Regenerate exe/actions/scan_hard.png (Ping / hard scan toolbar).

MDL2 globe (U+E909) — “whole network” sweep vs ARP scan’s circular arrows (U+E895).
Run on Windows, then: python tools/sync_assets_pngs.py
"""
from __future__ import annotations

from pathlib import Path

from mdl2_toolbar_icon import DEFAULT_FG, render_mdl2_png

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "exe" / "actions" / "scan_hard.png"
GLYPH = "\uE909"


def main() -> None:
    render_mdl2_png(OUT, 127, 127, GLYPH, fg=DEFAULT_FG)
    print(f"Wrote {OUT} (127x127)")


if __name__ == "__main__":
    main()
