"""Regression: f-strings must not mangle _PS_HOTSPOT_HELPERS brace literals."""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import clumsy_ics as ics


class ClumsyPsComposeTests(unittest.TestCase):
    def test_compose_preserves_hotspot_helper_braces(self) -> None:
        script = ics._compose_ps_script(
            "header\n",
            ics._PS_HOTSPOT_HELPERS,
            "footer\n",
        )
        self.assertIn("function Detect-ClumsyConsolePath", script)
        self.assertIn("NormGuidHotspot", script)
        self.assertIn("Trim('{','}')", script)
        self.assertIn("@{ Up = $det.Up; Down = $det.Down }", script)

    def test_enable_script_uses_compose_not_inline_fstring_helpers(self) -> None:
        import inspect

        src = inspect.getsource(ics.ensure_clumsy_ics_enabled)
        self.assertIn('_compose_ps_script(', src)
        self.assertNotIn('{_PS_HOTSPOT_HELPERS}', src)


if __name__ == '__main__':
    unittest.main()
