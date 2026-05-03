"""
Render Segoe MDL2 Assets glyphs into toolbar PNGs: maximize icon size within the
canvas so Qt’s 40×40 icon area is filled (uniform scale, small outer margin).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from toolbar_icon_color import DEFAULT_FG
DEFAULT_FONT = Path(r"C:\Windows\Fonts\segmdl2.ttf")


def _max_font_fit(
    font_path: Path,
    glyph: str,
    canvas_w: int,
    canvas_h: int,
    margin: float,
) -> ImageFont.FreeTypeFont:
    """Largest font size so glyph bbox fits inside (1-2*margin) of the canvas."""
    tw = canvas_w * (1.0 - 2.0 * margin)
    th = canvas_h * (1.0 - 2.0 * margin)
    lo, hi = 8, max(canvas_w, canvas_h) * 5
    best: ImageFont.FreeTypeFont | None = None
    scratch = Image.new("RGBA", (4, 4))
    draw = ImageDraw.Draw(scratch)
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            font = ImageFont.truetype(str(font_path), mid)
        except OSError:
            hi = mid - 1
            continue
        bbox = draw.textbbox((0, 0), glyph, font=font)
        gw = bbox[2] - bbox[0]
        gh = bbox[3] - bbox[1]
        if gw <= tw and gh <= th:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        return ImageFont.truetype(str(font_path), 24)
    return best


def render_mdl2_png(
    out_path: Path,
    out_w: int,
    out_h: int,
    glyph: str,
    *,
    font_path: Path | None = None,
    supersample: int = 4,
    margin: float = 0.05,
    fg: tuple[int, int, int, int] = DEFAULT_FG,
) -> None:
    fp = font_path or DEFAULT_FONT
    if not fp.is_file():
        print("Missing Segoe MDL2 Assets (expected at", fp, ")", file=sys.stderr)
        sys.exit(1)

    bw, bh = out_w * supersample, out_h * supersample
    font = _max_font_fit(fp, glyph, bw, bh, margin)

    big = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    bbox = draw.textbbox((0, 0), glyph, font=font)
    gw = bbox[2] - bbox[0]
    gh = bbox[3] - bbox[1]
    x = (bw - gw) / 2 - bbox[0]
    y = (bh - gh) / 2 - bbox[1]
    draw.text((x, y), glyph, font=font, fill=fg)

    img = big.resize((out_w, out_h), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG", optimize=True)
