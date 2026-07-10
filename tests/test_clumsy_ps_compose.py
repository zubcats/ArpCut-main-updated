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
        self.assertNotIn("\u2014", ics._PS_HOTSPOT_HELPERS)  # em dash breaks PS 5.1 ANSI parse
        self.assertIn("port - PC internet on", ics._PS_HOTSPOT_HELPERS)

    def test_enable_script_uses_compose_not_inline_fstring_helpers(self) -> None:
        import inspect

        # Public wrapper is thin; compose lives in the Windows impl.
        src = inspect.getsource(ics._ensure_clumsy_ics_enabled_impl)
        self.assertIn('_compose_ps_script(', src)
        self.assertNotIn('{_PS_HOTSPOT_HELPERS}', src)


if __name__ == '__main__':
    unittest.main()
