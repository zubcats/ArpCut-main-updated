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

    def test_lan_off_stops_pass_through_when_leftover_mitm_is_quiet(self) -> None:
        src = self._killer_py()
        ensure = src[src.index('def _ensure_restore_pass') : src.index('def _unblock_victim_firewall')]
        self.assertIn('_arm_restore_pass_stop', ensure)
        self.assertNotIn('_hold_restore_pass', src)
        self.assertNotIn('24.0 * 3600.0', src)
        self.assertNotIn('_RESTORE_PASS_S = 60.0', src)
        arm = src[src.index('def _arm_restore_pass_stop') : src.index('def _start_restore_pass_forwarder')]
        self.assertIn('_stop_restore_pass_forwarders', arm)
        reseal = arm[
            arm.index('if not _forwarder_is_pass_all') : arm.index(
                '_slide_until(now + _RESTORE_PASS_BUSY_SLIDE_S)'
            )
        ]
        self.assertIn('resume_percent_cut_live', reseal)
        self.assertNotIn('_stop_restore_pass_forwarders', reseal)
        mitm = os.path.join(_SRC, 'gui', 'impairment_mitm.py')
        with open(mitm, encoding='utf-8') as fh:
            rec = fh.read()
        rec = rec[rec.index('def _reconcile_idle_mitm_state') :]
        self.assertIn('if pass_all:', rec)
        self.assertNotIn('if pass_all and until', rec)
        fwd = os.path.join(_SRC, 'networking', 'forwarder.py')
        with open(fwd, encoding='utf-8') as fh:
            fsrc = fh.read()
        self.assertIn('def _l2_addressed_to_us', fsrc)
        process = fsrc[fsrc.index('def _process_packet') : fsrc.index('def _note_send_error')]
        self.assertLess(process.index('_l2_addressed_to_us'), process.index('self._pkt_count += 1'))

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

    def test_cut_after_off_does_not_rearm_kill(self) -> None:
        src = self._killer_py()
        apply = src[src.index('def apply_percent_cut') : src.index('def disable_percent_cut')]
        self.assertIn('arm_if_needed=False', src[src.index('def _apply_traffic_cut_sync') : src.index('def apply_traffic_cut')])
        self.assertIn('if not arm_if_needed:', apply)
        self.assertIn('self.kill(victim, wait_after=0.0, traffic_cut=False)', apply)
        cut = src[src.index('def _apply_traffic_cut_sync') : src.index('def apply_traffic_cut')]
        self.assertIn('arm_if_needed=False', cut)
        self.assertIn('apply_percent_cut', cut)
        after = apply[apply.index('self.forwarders[mac] = fw') :]
        self.assertIn('resume_percent_cut_live', after)
        self.assertNotIn('_stop_forwarder', after)

    def test_seal_hard_drop_reverts_if_unkill_won(self) -> None:
        src = self._killer_py()
        seal = src[src.index('def _seal_hard_drop') : src.index('def reinforce_full_cut')]
        self.assertIn('pass_all_live', seal)
        self.assertIn('with self._cut_gate()', seal)
        self.assertGreater(seal.rindex('mac not in self.killed'), seal.index('drop_from_victim = True'))

    def test_unkill_pops_mac_aliases(self) -> None:
        src = self._killer_py()
        unkill = src[src.index('def unkill') : src.index('def reinforce_restore')]
        self.assertIn('_killed_keys_for_victim', unkill)
        self.assertIn('_resume_percent_cut_live_unlocked', unkill)
        self.assertIn('_reassert_restore_pass', src[src.index('def _ensure_restore_pass') : src.index('def _unblock_victim_firewall')])

    def test_probe_aborts_when_op_seq_changes(self) -> None:
        path = os.path.join(_SRC, 'gui', 'impairment_mitm.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        probe = src[src.index('def _schedule_mitm_traffic_probe') : src.index('def _retry_mitm_on_arp_iface')]
        self.assertIn("_op_seq", probe)
        retry = src[src.index('def _retry_mitm_on_arp_iface') : src.index('def _clear_mitm_probe_retry')]
        self.assertIn('_mitm_arm_still_wanted', retry)
        self.assertGreater(retry.rindex('mac not in getattr(self.killer, \'killed\''), retry.index('_ensure_network_context_for_victim'))

    def test_arm_aborts_after_flow_off(self) -> None:
        path = os.path.join(_SRC, 'gui', 'impairment_blocks.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('def _mitm_arm_still_wanted', src)
        arm = src[src.index('def _arm_victim_mitm_like_kill') : src.index('def _arm_dupe_mitm_like_kill')]
        self.assertIn('_mitm_arm_still_wanted', arm)
        self.assertLess(arm.index('_mitm_arm_still_wanted'), arm.index('self.killer.kill'))
        kill = os.path.join(_SRC, 'gui', 'impairment_kill.py')
        with open(kill, encoding='utf-8') as fh:
            ksrc = fh.read()
        sched = ksrc[ksrc.index('def _schedule_kill_command') : ksrc.index('def _run_kill_command')]
        self.assertIn('_kill_intent_seq', sched)
        run = ksrc[ksrc.index('def _run_kill_command') : ksrc.index('def _schedule_kill_off_reinforce')]
        self.assertIn('lan_instant_aborted', run)
        self.assertIn('intent_seq', run)

    def test_lan_restore_arp_is_short_then_silent(self) -> None:
        src = self._killer_py()
        worker = src[src.index('def _unkill_restore_worker') : src.index('def kill_all')]
        self.assertIn('(0.45, 2)', worker)
        self.assertNotIn('(2.5, 2)', worker)
        self.assertNotIn('(120.0, 2)', worker)
        self.assertNotIn('(80.0, 2)', worker)
        self.assertNotIn('(1.0, 2)', worker)


if __name__ == '__main__':
    unittest.main()
