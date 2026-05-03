#!/usr/bin/env python3
"""
Build exe/zubcut_shell.ico for PyInstaller on Windows. Multi-resolution ICO makes the
taskbar/pinned shortcut glyph read larger than a single PNG embedded as the Win32 icon.

Crop per embedded size must match src/tools/logo_shell_crop.shell_content_fraction_for_target_px
(Qt uses the same tiers via branding.load_shell_application_qicon).
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.logo_shell_crop import shell_content_fraction_for_target_px  # noqa: E402

_LOGO = os.path.join(_ROOT, 'exe', 'zubcut_icon.png')
_OUT = os.path.join(_ROOT, 'exe', 'zubcut_shell.ico')

_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _crop_square_center(im, fraction: float):
    w, h = im.size
    if w < 2 or h < 2 or fraction >= 1.0:
        return im
    side = max(1, int(min(w, h) * fraction))
    x = (w - side) // 2
    y = (h - side) // 2
    return im.crop((x, y, x + side, y + side))


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print('build_windows_app_icon: Pillow not installed; skip ICO generation.', file=sys.stderr)
        return 1
    if not os.path.isfile(_LOGO):
        print(f'build_windows_app_icon: missing {_LOGO}', file=sys.stderr)
        return 1
    im = Image.open(_LOGO).convert('RGBA')
    images = []
    for s in _SIZES:
        frac = shell_content_fraction_for_target_px(s)
        master = _crop_square_center(im, frac)
        images.append(master.resize((s, s), Image.Resampling.LANCZOS))
    # Pillow only embeds sizes <= the first image's width/height; a 16×16 first frame
    # drops every larger layer (Explorer then upscales → zoomed/pixelated shortcuts).
    images.sort(key=lambda i: i.size[0], reverse=True)
    images[0].save(_OUT, format='ICO', append_images=images[1:])
    print(f'Wrote {_OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
