"""WinDivert lag gate resume_from_pause helper."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.ics_windivert_shaper import IcsWinDivertLagGate


class TestIcsWinDivertResume(unittest.TestCase):
    def test_resume_from_pause_clears_blocking(self) -> None:
        gate = IcsWinDivertLagGate('192.168.137.50')
        gate.set_blocking(True, mode='pause')
        gate.resume_from_pause()
        self.assertFalse(gate.is_blocking)


if __name__ == '__main__':
    unittest.main()
