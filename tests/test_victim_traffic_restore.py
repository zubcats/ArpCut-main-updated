"""PS5 traffic must fully restore when Kill/Lag/Dupe UI turns OFF."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestVictimTrafficRestore(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_release_victim_arp_mitm_stack_exists(self) -> None:
        src = self._main_py()
        self.assertIn('def _release_victim_arp_mitm_stack', src)
        self.assertIn('def _victim_teardown_ips', src)

    def test_emergency_release_detects_orphan_gate(self) -> None:
        src = self._main_py()
        block = src[src.index('def _ics_emergency_release'): src.index('def _ics_teardown_gate_if_idle')]
        self.assertIn('_ics_gate_matches_device(device)', block)
        self.assertIn('gate_live', block)

    def test_dupe_release_always_clears_arp_stack(self) -> None:
        src = self._main_py()
        fn = src[src.index('def _release_dupe_victim_immediate'): src.index('def _apply_victim_block')]
        self.assertIn('_release_victim_arp_mitm_stack(device)', fn)
        self.assertNotIn('return\n', fn[fn.index('_ics_emergency_release'): fn.index('_release_victim_arp_mitm_stack')])

    def test_deferred_dupe_clear_teardowns_windivert_net(self) -> None:
        src = self._main_py()
        fn = src[src.index('def _do_deferred_dupe_clear'): src.index('@pyqtSlot()', src.index('def _do_deferred_dupe_clear'))]
        self.assertIn('if self._uses_windivert(snap):', fn)
        self.assertIn('_finish_dupe_ics_teardown_net(snap)', fn)

    def test_stop_lag_reinforces_mitm_teardown(self) -> None:
        src = self._main_py()
        stop = src[src.index('def stopLagSwitch'): src.index('def startDupe', src.index('def stopLagSwitch'))]
        self.assertIn('_release_victim_arp_mitm_stack(device)', stop)

    def test_kill_off_uses_full_arp_stack_release(self) -> None:
        src = self._main_py()
        kill = src[src.index('def _run_kill_command'): src.index('def _schedule_kill_off_reinforce')]
        off = kill[kill.index('else:'):]
        self.assertIn('_release_victim_arp_mitm_stack(victim)', off)
        self.assertIn('_ensure_network_context_for_victim(device, fast=True)', src[src.index('def _release_victim_arp_mitm_stack'): src.index('def _ics_gate_allow_traffic')])


if __name__ == '__main__':
    unittest.main()
