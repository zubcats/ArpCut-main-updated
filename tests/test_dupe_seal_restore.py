"""Dupe: post-instant seal for full cut; sync restore when UI turns OFF."""
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


class TestDupeSealRestore(unittest.TestCase):
    def test_seal_helper_is_post_instant_only(self) -> None:
        src = load_main_window_source()
        self.assertIn('def _seal_lan_mitm_after_instant_cut', src)
        seal = method_src('_seal_lan_mitm_after_instant_cut')
        self.assertIn('disable_ip_forwarding', seal)
        self.assertIn('_reinforce_full_cut_async', seal)
        self.assertIn('_bg_block_ip', seal)
        self.assertIn("mac not in getattr(self.killer, 'killed', {})", seal)
        self.assertLess(
            seal.index("mac not in getattr(self.killer, 'killed', {})"),
            seal.index('_bg_block_ip'),
        )
        self.assertIn('_log_mitm_arm_status', seal)
        self.assertIn('red chain', seal.lower())
        # Must not call kill()/poison — those stay on the instant preblock path.
        self.assertNotIn('killer.kill(', seal)
        self.assertNotIn('_poison_arp_now', seal)

    def test_preblock_live_dupe_arm_seals_after_cut(self) -> None:
        arm = method_src('_run_dupe_arm_command')
        pre = arm[arm.index("if getattr(self, '_dupe_preblocked', False)"):]
        pre = pre.split("preblock did not stick", 1)[0]
        seal_at = pre.index('_seal_lan_mitm_after_instant_cut')
        # Instant reassert/cut stay before seal.
        self.assertLess(pre.index('reassert_poison'), seal_at)
        self.assertLess(pre.index('_apply_traffic_cut_sync'), seal_at)
        self.assertLess(pre.index('_dupe_impairment_is_live(dev)'), seal_at)
        self.assertIn("action='Dupe'", pre)
        self.assertIn('_dupe_start_gen', pre)

    def test_start_dupe_keeps_instant_preblock_before_arm(self) -> None:
        start = methods_through('startDupe', 'dupe_remaining_ms')
        pre = start.index("_flow_instant_preblock(device, direction, flow='Dupe')")
        arm = start.index('_schedule_dupe_arm_command')
        self.assertLess(pre, arm)
        # Seal must not run on the click path before preblock.
        click = start[:pre]
        self.assertNotIn('_seal_lan_mitm_after_instant_cut', click)

    def test_stop_dupe_unkills_sync_and_bumps_gen(self) -> None:
        stop = method_src('stopDupe')
        self.assertIn('_dupe_start_gen', stop)
        paint = stop.index("btnDupe.setText('Dupe')")
        release = stop.index('_release_dupe_victim_immediate(release_snap, refresh_context=False)')
        self.assertLess(paint, release)
        paint_events = stop.index('processEvents')
        self.assertLess(paint_events, release)
        self.assertNotIn('QTimer.singleShot(0, _release_on_gui)', stop)
        # Deferred clear stays firewall-only (ARP already restored sync).
        deferred = method_src('_do_deferred_dupe_clear')
        self.assertNotIn('killer.unkill', deferred)
        # Delayed OFF reinforce re-entered Npcap/_ensure_network_context on the GUI
        # thread ~25ms later and froze ZubCut while the button still showed DUPE.
        self.assertNotIn('_schedule_flow_off_reinforce', stop)
        self.assertNotIn('_schedule_dupe_off_reinforce', method_src('_release_dupe_victim_immediate'))

    def test_forwarder_stop_closes_npcap_off_caller_thread(self) -> None:
        path = os.path.join(_ROOT, 'src', 'networking', 'forwarder.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        stop = src[src.index('    def stop(self):') : src.index('    def get_stats(')]
        self.assertIn('def _stop_sniff()', stop)
        self.assertLess(stop.index('def _stop_sniff()'), stop.index('sock.close()'))
        self.assertNotIn('self._socket.close()', stop)

    def test_full_cut_seal_aborts_after_unkill_seq(self) -> None:
        path = os.path.join(_ROOT, 'src', 'networking', 'killer.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        body = src[
            src.index('    def reinforce_full_cut(') : src.index('    def _reinforce_full_cut_async(')
        ]
        self.assertIn('_op_seq.get(mac, 0)', body)
        apply = src[src.index('    def apply_percent_cut(') : src.index('    def disable_percent_cut(')]
        self.assertIn('_seal_hard_drop(mac)', apply)


if __name__ == '__main__':
    unittest.main()
