"""LAN Kill OFF must keep pass-through until leftover MITM is quiet."""
from __future__ import annotations

import os
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')


class TestRestorePassHold(unittest.TestCase):
    def _killer_py(self) -> str:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_lan_off_holds_pass_through_until_next_on(self) -> None:
        src = self._killer_py()
        ensure = src[src.index('def _ensure_restore_pass') : src.index('def _unblock_victim_firewall')]
        self.assertIn('_hold_restore_pass', ensure)
        self.assertNotIn('_arm_restore_pass_stop', ensure)
        self.assertNotIn('_RESTORE_PASS_S = 60.0', src)
        mitm = os.path.join(_SRC, 'gui', 'impairment_mitm.py')
        with open(mitm, encoding='utf-8') as fh:
            rec = fh.read()
        rec = rec[rec.index('def _reconcile_idle_mitm_state') :]
        self.assertIn('if pass_all:', rec)
        self.assertNotIn('if pass_all and until', rec)

    def test_wifi_restore_broadcasts_consistent_router_sa(self) -> None:
        src = self._killer_py()
        block = src[src.index('def _restore_frames') : src.index('def _restore_arp_now')]
        self.assertIn("Ether(src=router_mac, dst=bcast)", block)
        self.assertIn('hwsrc=router_mac', block)
        self.assertIn('Undo poison with the same delivery', block)

    def test_flow_off_reinforce_does_not_unkill_again(self) -> None:
        path = os.path.join(_SRC, 'gui', 'impairment_kill.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        block = src[
            src.index('def _schedule_flow_off_reinforce') : src.index(
                'def _kill_ui_shows_on'
            )
        ]
        self.assertIn('reinforce_restore', block)
        self.assertNotIn('self.killer.unkill(victim)', block)

    def test_lan_restore_arp_is_short_then_silent(self) -> None:
        src = self._killer_py()
        worker = src[src.index('def _unkill_restore_worker') : src.index('def kill_all')]
        self.assertIn('(0.45, 2)', worker)
        self.assertNotIn('(120.0, 2)', worker)
        self.assertNotIn('(80.0, 2)', worker)
        self.assertNotIn('(1.0, 2)', worker)


if __name__ == '__main__':
    unittest.main()
