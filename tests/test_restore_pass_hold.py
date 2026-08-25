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

    def test_restore_pass_waits_for_quiet_not_fixed_60s(self) -> None:
        src = self._killer_py()
        self.assertIn('_RESTORE_PASS_MIN_S = 180.0', src)
        self.assertIn('_RESTORE_PASS_QUIET_S = 45.0', src)
        self.assertNotIn('_RESTORE_PASS_S = 60.0', src)
        self.assertNotIn('_RESTORE_PASS_MAX_S', src)
        arm = src[src.index('def _arm_restore_pass_stop') : src.index('def _start_restore_pass_forwarder')]
        self.assertIn('_restore_pass_seen', arm)
        self.assertIn('_forwarder_is_pass_all', arm)
        self.assertIn('_RESTORE_PASS_BUSY_SLIDE_S', arm)
        self.assertIn('Never stop while leftover MITM is still delivering', src)
        self.assertIn('packets_seen', src[src.index('def _restore_pass_seen') : src.index('def _arm_restore_pass_stop')])
        self.assertNotIn('sleep(_RESTORE_PASS_S)', arm)
        self.assertNotIn('while monotonic() - started < _RESTORE_PASS_MIN_S', arm)

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

    def test_lan_restore_arp_covers_pass_through_window(self) -> None:
        src = self._killer_py()
        worker = src[src.index('def _unkill_restore_worker') : src.index('def kill_all')]
        self.assertIn('(120.0, 2)', worker)
        self.assertIn('(80.0, 2)', worker)
        self.assertIn('(10.0, 2)', worker)


if __name__ == '__main__':
    unittest.main()
