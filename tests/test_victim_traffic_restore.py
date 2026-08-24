"""PS5 traffic must fully restore when Kill/Lag/Dupe UI turns OFF."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _gui_source import load_main_window_source, methods_through, method_src


class TestVictimTrafficRestore(unittest.TestCase):
    def _main_py(self) -> str:
        return load_main_window_source()

    def test_release_victim_arp_mitm_stack_exists(self) -> None:
        src = self._main_py()
        self.assertIn('def _release_victim_arp_mitm_stack', src)
        self.assertIn('def _victim_teardown_ips', src)

    def test_emergency_release_detects_orphan_gate(self) -> None:
        src = self._main_py()
        block = methods_through('_ics_emergency_release', '_ics_teardown_gate_if_idle')
        self.assertIn('_ics_gate_matches_device(device)', block)
        self.assertIn('gate_live', block)

    def test_dupe_release_always_clears_arp_stack(self) -> None:
        src = self._main_py()
        fn = methods_through('_release_dupe_victim_immediate', '_apply_victim_block')
        self.assertIn('_release_victim_arp_mitm_stack(device, refresh_context=refresh_context)', fn)
        self.assertNotIn(
            'return\n',
            fn[fn.index('_ics_emergency_release'): fn.index('_release_victim_arp_mitm_stack')],
        )

    def test_deferred_dupe_clear_teardowns_windivert_net(self) -> None:
        src = self._main_py()
        fn = method_src('_do_deferred_dupe_clear')
        self.assertIn('if self._uses_windivert(snap):', fn)
        self.assertIn('_finish_dupe_ics_teardown_net(snap)', fn)

    def test_stop_lag_reinforces_mitm_teardown(self) -> None:
        src = self._main_py()
        stop = methods_through('stopLagSwitch', 'startDupe')
        self.assertIn('_release_victim_arp_mitm_stack(device)', stop)

    def test_kill_off_uses_full_arp_stack_release(self) -> None:
        src = self._main_py()
        kill = methods_through('_run_kill_command', '_schedule_kill_off_reinforce')
        off = kill[kill.index('else:'):]
        self.assertIn('_release_victim_arp_mitm_stack(victim)', off)
        self.assertIn('_ensure_network_context_for_victim(device, fast=True)', methods_through('_release_victim_arp_mitm_stack', '_ics_gate_allow_traffic'))

    def test_lan_release_stops_npcap_forwarder(self) -> None:
        fn = methods_through('_release_victim_arp_mitm_stack', '_ics_gate_allow_traffic')
        self.assertIn('self.killer.disable_percent_cut(mac)', fn)
        self.assertNotIn('LAN Kill OFF keeps the Npcap forwarder', fn)
        ics_at = fn.index('is_ics = self._is_ics_downstream(victim)')
        disable_at = fn.index('disable_percent_cut')
        self.assertLess(ics_at, disable_at)
        self.assertNotIn('if is_ics:', fn[ics_at:disable_at])

    def test_ics_emergency_does_not_treat_lan_killed_as_ics(self) -> None:
        block = methods_through('_ics_emergency_release', '_ics_teardown_gate_if_idle')
        probe = block[block.index('has_ics_state'): block.index('if not plan.is_ics_downstream')]
        self.assertNotIn('killer.killed', probe)
        self.assertIn('_ics_kill_profile_macs', probe)
        self.assertIn('_ics_windivert_busy', probe)


if __name__ == '__main__':
    unittest.main()
