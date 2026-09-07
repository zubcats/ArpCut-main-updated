"""Old Clumsy ICS PowerShell helpers must stay gone."""

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
    def test_hotspot_sharing_powershell_is_gone(self) -> None:
        self.assertFalse(hasattr(ics, '_PS_HOTSPOT_HELPERS'))
        self.assertFalse(hasattr(ics, '_compose_ps_script'))
        self.assertFalse(hasattr(ics, '_ensure_clumsy_ics_enabled_impl'))
        src_path = os.path.join(_SRC, 'tools', 'clumsy_ics.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        self.assertNotIn('HNetShare', src)
        self.assertNotIn('EnableSharing', src)
        self.assertNotIn('netsh wlan stop hostednetwork', src)


if __name__ == '__main__':
    unittest.main()
