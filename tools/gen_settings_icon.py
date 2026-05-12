"""
Regenerate exe/actions/settings.png (toolbar Settings).

Segoe MDL2 Assets + maximize glyph fill (see mdl2_toolbar_icon.py).
Run on Windows, then: python tools/sync_assets_pngs.py
"""
from __future__ import annotations

from pathlib import Path

from mdl2_toolbar_icon import DEFAULT_FG, render_mdl2_png

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "exe" / "actions" / "settings.png"
# MDL2 "Settings" (gear)
GLYPH = "\uE713"

# Match scan_easy canvas so the gear scales like other toolbar icons (no extra letterboxing).
OUT_W, OUT_H = 115, 127


def main() -> None:
    render_mdl2_png(OUT, OUT_W, OUT_H, GLYPH, fg=DEFAULT_FG, margin=0.04)
    print(f"Wrote {OUT} ({OUT_W}x{OUT_H})")


if __name__ == "__main__":
    main()
