"""Toolbar glyph colour: same sage as Me/Router rows (ADMIN_DEVICE_TABLE_ROW_BG)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_src = _ROOT / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import constants as _zcut_constants  # noqa: E402


def toolbar_icon_fg() -> tuple[int, int, int, int]:
    hex_s = getattr(_zcut_constants, "ADMIN_DEVICE_TABLE_ROW_BG", "#5D706E").lstrip("#")
    if len(hex_s) != 6:
        hex_s = "5D706E"
    r = int(hex_s[0:2], 16)
    g = int(hex_s[2:4], 16)
    b = int(hex_s[4:6], 16)
    return (r, g, b, 255)


DEFAULT_FG = toolbar_icon_fg()
