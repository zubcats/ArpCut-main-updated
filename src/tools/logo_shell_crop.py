"""
Crop fractions for Windows shell surfaces (exe .ico + Qt QIcon per-size ladder).

A single aggressive crop made Explorer's large shortcut / preview layers look wildly
zoomed-in while small taskbar pixels stayed hard to read. We use a tighter crop only
for sizes Windows typically uses at ≤48px (taskbar, list rows) and a looser crop for
larger layers (desktop shortcuts, hover thumbnails).
"""
from __future__ import annotations

_SHELL_SMALL_MAX_PX = 48
# ≤48px (taskbar, lists): tighter crop than mid/large layers so the mark reads larger.
_FRACTION_LEQ_48 = 0.34
# >48px (desktop shortcuts, hover, 256px ICO): looser crop so the logo is not over-zoomed.
_FRACTION_GT_48 = 0.58


def shell_content_fraction_for_target_px(size: int) -> float:
    if size <= 0:
        return _FRACTION_GT_48
    if size <= _SHELL_SMALL_MAX_PX:
        return _FRACTION_LEQ_48
    return _FRACTION_GT_48
