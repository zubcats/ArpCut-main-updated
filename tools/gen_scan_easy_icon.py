"""
Regenerate exe/actions/scan_easy.png (ARP scan toolbar).

Uses Segoe MDL2 Assets glyph U+E895 (Sync / circular arrows). Run on Windows
where segmdl2.ttf exists, then: python tools/sync_assets_pngs.py

Glyph is scaled to maximize fill inside the PNG (matches Settings icon workflow).
"""
from __future__ import annotations

from pathlib import Path

from mdl2_toolbar_icon import DEFAULT_FG, render_mdl2_png

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "exe" / "actions" / "scan_easy.png"
# MDL2 "Sync" / circular double-arrow (matches common scan/refresh metaphor)
GLYPH = "\uE895"


def main() -> None:
    # Toolbar displays icons at 40×40; asset aspect preserved from legacy bundle.
    render_mdl2_png(OUT, 115, 127, GLYPH, fg=DEFAULT_FG)
    print(f"Wrote {OUT} (115x127)")


if __name__ == "__main__":
    main()
