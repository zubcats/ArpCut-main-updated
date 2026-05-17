"""ICS WinDivert blocking-mode packet handling."""
from __future__ import annotations

import inspect
import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import ics_windivert_shaper as wd


class TestIcsWinDivertBlocking(unittest.TestCase):
    def test_percent_loss_does_not_drop_allowed_packets_twice(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        block = src[src.index('if blocking:'): src.index('if shaping and')]
        self.assertIn('_send_immediate', block)
        self.assertNotRegex(
            block,
            r'elif loss_pct > 0:\s*\n\s*continue',
        )


if __name__ == '__main__':
    unittest.main()
