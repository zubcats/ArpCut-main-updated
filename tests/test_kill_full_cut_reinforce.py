"""Kill full-cut reinforce must run after instant poison/cut, never before."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestKillFullCutReinforce(unittest.TestCase):
    @staticmethod
    def _killer_py() -> str:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_kill_schedules_reinforce_after_instant_cut(self) -> None:
        src = self._killer_py()
        kill = src[src.index('def kill(') : src.index('def _apply_traffic_cut_sync')]
        poison_at = kill.index('_poison_arp_now')
        cut_at = kill.index('_apply_traffic_cut_sync')
        disable_at = kill.index('disable_ip_forwarding')
        reinforce_at = kill.index('_reinforce_full_cut_async')
        self.assertLess(poison_at, cut_at)
        self.assertLess(cut_at, disable_at)
        self.assertLess(disable_at, reinforce_at)
        self.assertIn('aggressive=bool(traffic_cut and not ics_mode)', kill)
        # Reinforce only when traffic_cut (full Kill), not MITM-only arms.
        self.assertIn('if not ics_mode and traffic_cut:', kill)
        self.assertIn('self._reinforce_full_cut_async(victim)', kill)

    def test_reinforce_full_cut_does_not_bump_op_seq(self) -> None:
        src = self._killer_py()
        block = src[
            src.index('def reinforce_full_cut') : src.index('def _reinforce_full_cut_async')
        ]
        self.assertIn('reassert_poison', block)
        self.assertIn('_apply_traffic_cut_sync', block)
        self.assertIn('disable_ip_forwarding', block)
        self.assertIn('_seal_hard_drop', block)
        self.assertNotIn('_next_op_seq', block)
        self.assertNotIn('self.kill(', block)

    def test_reinforce_async_yields_before_work(self) -> None:
        src = self._killer_py()
        block = src[
            src.index('def _reinforce_full_cut_async') : src.index('def _poison_frames')
        ]
        self.assertIn("name='zubcut-kill-full-cut'", block)
        self.assertIn('sleep(0.02)', block)
        self.assertIn('reinforce_full_cut', block)
        # Must not run reinforce on the caller thread before returning from kill().
        self.assertNotIn('self.reinforce_full_cut(victim)', block.split('def _work')[0])

    def test_aggressive_arp_warmup_for_kill(self) -> None:
        src = self._killer_py()
        worker = src[
            src.index('def _kill_arp_worker') : src.index('def unkill(')
        ]
        self.assertIn('aggressive=False', worker)
        self.assertIn('warmup_remaining = 8', worker)
        self.assertIn('warmup_gap = 0.05', worker)

    def test_gui_rearm_path_schedules_reinforce_after_cut(self) -> None:
        path = os.path.join(_SRC, 'gui', 'impairment_kill.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        block = src[
            src.index("elif turn_on and mac in self.killer.killed:") : src.index(
                "else:\n                        _mark('lan_start')"
            )
        ]
        poison_at = block.index('reassert_poison')
        cut_at = block.index('_apply_traffic_cut_sync')
        reinforce_at = block.index('_reinforce_full_cut_async')
        self.assertLess(poison_at, cut_at)
        self.assertLess(cut_at, reinforce_at)
        self.assertIn('_apply_lan_kill_full', block)


if __name__ == '__main__':
    unittest.main()
