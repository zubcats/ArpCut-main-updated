"""
Crop fractions for Windows shell surfaces (exe .ico + Qt QIcon per-size ladder).

A single aggressive crop made Explorer's large shortcut / preview layers look wildly
zoomed-in while small taskbar pixels stayed hard to read. We use a tighter crop only
for sizes Windows typically uses at ≤48px (taskbar, list rows) and a looser crop for
larger layers (desktop shortcuts, hover thumbnails).
"""
from __future__ import annotations

# Taskbar / tray mostly asks for ≤32px; keep a tighter crop only there so the mark reads larger.
_SHELL_TIGHT_MAX_PX = 32
_FRACTION_LEQ_32 = 0.34
# Match tools.branding.LOGO_UI_CONTENT_FRACTION: same framing as in-app / license-style shortcuts
# (Explorer large icons & hover were still over-zoomed at 0.58).
_FRACTION_SHELL_LARGE = 0.64


def shell_content_fraction_for_target_px(size: int) -> float:
    if size <= 0:
        return _FRACTION_SHELL_LARGE
    if size <= _SHELL_TIGHT_MAX_PX:
        return _FRACTION_LEQ_32
    return _FRACTION_SHELL_LARGE
