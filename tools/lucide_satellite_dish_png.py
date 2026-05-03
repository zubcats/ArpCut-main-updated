"""
Rasterize Lucide \"satellite-dish\" (ISC license — https://lucide.dev/icons/satellite-dish)
to a toolbar PNG. Pure Pillow + svg.path (no system Cairo).

Stroke colour matches Me/Router sage (ADMIN_DEVICE_TABLE_ROW_BG).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw
from svg.path import Path as SvgPath
from svg.path import parse_path

from toolbar_icon_color import DEFAULT_FG

# Lucide icons/satellite-dish.svg — viewBox 0 0 24 24
_LUCIDE_PATHS = [
    "M4 10a7.31 7.31 0 0 0 10 10Z",
    "m9 15 3-3",
    "M17 13a6 6 0 0 0-6-6",
    "M21 13A10 10 0 0 0 11 3",
]


def _flatten(path: SvgPath, steps_per_unit: float = 6.0) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for seg in path:
        try:
            ln = float(seg.length())
        except Exception:
            ln = 10.0
        n = max(12, min(96, int(ln * steps_per_unit)))
        for i in range(n + 1):
            z = seg.point(i / n)
            pts.append((z.real, z.imag))
    return pts


def render_lucide_satellite_dish_png(
    out_path: Path,
    out_w: int,
    out_h: int,
    *,
    supersample: int = 4,
    fg: tuple[int, int, int, int] = DEFAULT_FG,
    margin_frac: float = 0.08,
) -> None:
    bw, bh = out_w * supersample, out_h * supersample
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    mx = bw * margin_frac
    my = bh * margin_frac
    span = min(bw - 2 * mx, bh - 2 * my)
    scale = span / 24.0
    # Lucide default stroke is 2 in 24px space — slightly lighter when supersampled.
    sw = max(2.2, 2.0 * scale * 0.78)

    for d_str in _LUCIDE_PATHS:
        path = parse_path(d_str)
        flat = _flatten(path)
        scr = [(mx + x * scale, my + y * scale) for x, y in flat]
        if len(scr) >= 2:
            d.line(scr, fill=fg, width=int(round(sw)), joint="curve")

    out_img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(out_path, format="PNG", optimize=True)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    render_lucide_satellite_dish_png(root / "exe" / "actions" / "scan_hard.png", 127, 127)
    print(f"Wrote {root / 'exe/actions/scan_hard.png'} (Lucide satellite-dish)")


if __name__ == "__main__":
    main()
