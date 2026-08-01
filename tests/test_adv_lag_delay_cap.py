"""Advanced Lag delay/jitter share the MITM forwarder max (raised above 800ms)."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestAdvLagDelayCap(unittest.TestCase):
    def test_forwarder_max_delay_is_at_least_one_second(self) -> None:
        path = os.path.join(_SRC, 'networking', 'forwarder.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('_MAX_DELAY_MS = 5000', src)
        self.assertNotIn('_MAX_DELAY_MS = 800', src)

    def test_ui_and_sched_use_forwarder_constant(self) -> None:
        adv = os.path.join(_SRC, 'gui', 'advanced_lag_settings.py')
        sched = os.path.join(_SRC, 'tools', 'mitm_adv_sched.py')
        with open(adv, encoding='utf-8') as f:
            adv_src = f.read()
        with open(sched, encoding='utf-8') as f:
            sched_src = f.read()
        self.assertIn('_MAX_DELAY_MS', adv_src)
        self.assertIn('s.setRange(0, int(_MAX_DELAY_MS))', adv_src)
        self.assertNotIn('s.setRange(0, 800)', adv_src)
        self.assertIn('_MAX_DELAY_MS', sched_src)
        self.assertNotIn('min(800,', sched_src)


if __name__ == '__main__':
    unittest.main()
