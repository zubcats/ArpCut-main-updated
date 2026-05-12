"""
Normalize a reference radar-dish PNG into exe/actions/scan_hard.png:
drop pink/near-white backdrop, map ink to Me/Router sage (ADMIN_DEVICE_TABLE_ROW_BG), letterbox to 127².

Default source: assets/reference_scan_hard_dish.png (drop your asset there, then run).
Then: python tools/sync_assets_pngs.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image

from toolbar_icon_color import toolbar_icon_fg

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "assets" / "reference_scan_hard_dish.png"
OUT = ROOT / "exe" / "actions" / "scan_hard.png"
OUT_SIZE = 127
# Sampled from user reference corners
_BG = (255, 243, 243)


def _bg_dist(r: int, g: int, b: int) -> float:
    return math.sqrt((r - _BG[0]) ** 2 + (g - _BG[1]) ** 2 + (b - _BG[2]) ** 2)


def normalize(src: Path, dst: Path, out_size: int = OUT_SIZE) -> None:
    fg = toolbar_icon_fg()
    im = Image.open(src).convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 12:
                px[x, y] = (0, 0, 0, 0)
                continue
            d = _bg_dist(r, g, b)
            if d < 42:
                px[x, y] = (0, 0, 0, 0)
            elif d < 58:
                # Anti-alias fringe vs backdrop
                t = (d - 42) / (58 - 42)
                px[x, y] = (*fg[:3], int(255 * max(0.0, min(1.0, t))))
            else:
                px[x, y] = fg

    bbox = im.split()[3].getbbox()
    if bbox:
        im = im.crop(bbox)

    sw, sh = im.size
    scale = min(out_size / sw, out_size / sh)
    nw = max(1, int(round(sw * scale)))
    nh = max(1, int(round(sh * scale)))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (out_size, out_size), (0, 0, 0, 0))
    ox = (out_size - nw) // 2
    oy = (out_size - nh) // 2
    canvas.paste(im, (ox, oy), im)

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, format="PNG", optimize=True)
    print(f"Wrote {dst} from {src}")


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src.is_file():
        raise SystemExit(f"Missing source PNG: {src}")
    normalize(src, OUT)


if __name__ == "__main__":
    main()
