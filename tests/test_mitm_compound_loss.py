"""Unit tests for compounded Advanced Lag loss."""

import os
import sys
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.mitm_compound_loss import effective_delivery_pct, survival_probability


class MitmCompoundLossTest(unittest.TestCase):
    def test_loss_only(self):
        self.assertAlmostEqual(
            survival_probability(50, cap_active=False, cap_can_forward=True),
            0.5,
        )

    def test_compound_loss_and_overflow(self):
        surv = survival_probability(
            50,
            cap_active=True,
            cap_can_forward=False,
            overflow_loss_pct=50,
        )
        self.assertAlmostEqual(surv, 0.25)

    def test_overflow_100_matches_always_drop_when_over_cap(self):
        surv = survival_probability(
            30,
            cap_active=True,
            cap_can_forward=False,
            overflow_loss_pct=100,
        )
        self.assertAlmostEqual(surv, 0.0)

    def test_under_cap_ignores_overflow(self):
        surv = survival_probability(
            50,
            cap_active=True,
            cap_can_forward=True,
            overflow_loss_pct=100,
        )
        self.assertAlmostEqual(surv, 0.5)

    def test_effective_delivery_pct(self):
        self.assertAlmostEqual(
            effective_delivery_pct(
                50,
                cap_active=True,
                cap_over_cap=True,
                overflow_loss_pct=50,
            ),
            25.0,
        )


if __name__ == '__main__':
    unittest.main()
