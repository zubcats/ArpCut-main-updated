"""Unit tests for Advanced Lag per-impairment timer gates."""

import os
import sys
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, 'src'))

from tools import mitm_adv_sched


def _g(**kwargs):
    base = {
        'mitm_adv_delay_timer_on': True,
        'mitm_adv_delay_timer_lag_ms': 100,
        'mitm_adv_delay_timer_pause_ms': 100,
        'mitm_adv_delay_timer_repeat_forever': True,
        'mitm_adv_delay_timer_runs': -1,
    }
    base.update(kwargs)

    def get(k, default=None):
        if k in base:
            return base[k]
        return default

    return get


class MitmAdvSchedTest(unittest.TestCase):
    def test_timer_off_always_one(self):
        get = _g(mitm_adv_delay_timer_on=False)
        self.assertEqual(mitm_adv_sched.gate_for_row(0.0, 0.0, get, 'mitm_adv_delay'), 1.0)
        self.assertEqual(mitm_adv_sched.gate_for_row(999.0, 0.0, get, 'mitm_adv_delay'), 1.0)

    def test_repeat_off_single_lag_window(self):
        get = _g(
            mitm_adv_delay_timer_repeat_forever=False,
            mitm_adv_delay_timer_lag_ms=200,
            mitm_adv_delay_timer_pause_ms=300,
        )
        self.assertEqual(mitm_adv_sched.gate_for_row(0.0, 0.0, get, 'mitm_adv_delay'), 1.0)
        self.assertEqual(mitm_adv_sched.gate_for_row(0.19, 0.0, get, 'mitm_adv_delay'), 1.0)
        self.assertEqual(mitm_adv_sched.gate_for_row(0.21, 0.0, get, 'mitm_adv_delay'), 0.0)
        self.assertEqual(mitm_adv_sched.gate_for_row(10.0, 0.0, get, 'mitm_adv_delay'), 0.0)

    def test_repeat_on_infinite_cycles(self):
        get = _g(
            mitm_adv_delay_timer_repeat_forever=True,
            mitm_adv_delay_timer_lag_ms=100,
            mitm_adv_delay_timer_pause_ms=100,
            mitm_adv_delay_timer_runs=-1,
        )
        t0 = 0.0
        # 0–0.1s on, 0.1–0.2s off, 0.2–0.3s on
        self.assertEqual(mitm_adv_sched.gate_for_row(0.05, t0, get, 'mitm_adv_delay'), 1.0)
        self.assertEqual(mitm_adv_sched.gate_for_row(0.15, t0, get, 'mitm_adv_delay'), 0.0)
        self.assertEqual(mitm_adv_sched.gate_for_row(0.25, t0, get, 'mitm_adv_delay'), 1.0)
        self.assertEqual(mitm_adv_sched.gate_for_row(10.04, t0, get, 'mitm_adv_delay'), 1.0)

    def test_repeat_on_finite_cycles(self):
        get = _g(
            mitm_adv_delay_timer_repeat_forever=True,
            mitm_adv_delay_timer_lag_ms=100,
            mitm_adv_delay_timer_pause_ms=100,
            mitm_adv_delay_timer_runs=2,
        )
        t0 = 0.0
        # period 0.2s, 2 cycles = 0.4s; inside window at 0.25 is lag phase of 2nd cycle
        self.assertEqual(mitm_adv_sched.gate_for_row(0.25, t0, get, 'mitm_adv_delay'), 1.0)
        self.assertEqual(mitm_adv_sched.gate_for_row(0.35, t0, get, 'mitm_adv_delay'), 0.0)
        self.assertEqual(mitm_adv_sched.gate_for_row(0.45, t0, get, 'mitm_adv_delay'), 0.0)

    def test_runs_zero_always_off(self):
        get = _g(
            mitm_adv_delay_timer_repeat_forever=True,
            mitm_adv_delay_timer_lag_ms=100,
            mitm_adv_delay_timer_pause_ms=100,
            mitm_adv_delay_timer_runs=0,
        )
        self.assertEqual(mitm_adv_sched.gate_for_row(0.0, 0.0, get, 'mitm_adv_delay'), 0.0)


if __name__ == '__main__':
    unittest.main()
