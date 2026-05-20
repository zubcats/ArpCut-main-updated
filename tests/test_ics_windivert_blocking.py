"""ICS WinDivert blocking-mode packet handling."""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import ics_windivert_shaper as wd


class TestIcsWinDivertBlocking(unittest.TestCase):
    def test_pause_drops_victim_packets_without_heap_hold(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        block = src[src.index('if impair_mode == IMPAIR_PAUSE'): src.index('self._send_immediate(h, dll, pkt, addr_b')]
        self.assertIn('continue', block)
        self.assertNotIn('_PAUSE_HOLD_DUE', block)
        self.assertNotIn('self._packets_held += 1', block)

    def test_percent_cut_uses_byte_budget_not_pause_hold(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate)
        self.assertIn('def apply_percent_cut', src)
        self.assertIn('_passes_byte_ratio', src)
        self.assertIn('IMPAIR_PERCENT', src)
        loop = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        self.assertIn('impair_mode == IMPAIR_PERCENT', loop)
        pct_block = loop[loop.index('if impair_mode == IMPAIR_PERCENT'): loop.index('if impair_mode == IMPAIR_SHAPE')]
        self.assertIn('_passes_byte_ratio', pct_block)
        self.assertNotIn('random.randint(1, 100)', pct_block)
        apply = src[src.index('def apply_percent_cut'): src.index('def apply_shaping_params')]
        self.assertIn('IMPAIR_PERCENT', apply)
        self.assertIn('self._blocking = False', apply)

    def test_percent_cut_duplicate_capture_passes_through(self) -> None:
        loop = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        dedupe = loop[loop.index('if sig:'): loop.index('if impair_mode == IMPAIR_PERCENT')]
        self.assertIn('self._send_immediate', dedupe)
        self.assertNotRegex(
            dedupe,
            r'if last is not None and \(now - last\) < 0\.05:\s*\n\s*continue\s*\n',
        )

    def test_apply_shaping_clears_blocking_and_percent_cut(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate.apply_shaping_params)
        self.assertIn('self._blocking = False', src)
        self.assertIn('_clear_percent_cut_unlocked', src)
        self.assertIn('self._discard_heap = True', src)

    def test_clear_blocking_pause_leaves_partial_modes_ready(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate.clear_blocking_pause)
        self.assertIn('self._blocking = False', src)
        self.assertIn('self._hold_pause = False', src)
        self.assertIn('self._discard_heap = True', src)

    def test_run_loop_partial_modes_before_blocking_pause(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        block_idx = src.rindex('if impair_mode == IMPAIR_PAUSE and blocking')
        pass_idx = src.index('if impair_mode == IMPAIR_PERCENT and')
        shape_idx = src.index('if impair_mode == IMPAIR_SHAPE and')
        off_fwd = src.index('if impair_mode == IMPAIR_OFF:\n                    self._send_immediate')
        self.assertLess(off_fwd, block_idx)
        self.assertLess(pass_idx, block_idx)
        self.assertLess(shape_idx, block_idx)

    def test_hotspot_percent_cut_uses_windivert_helper(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('def _ics_hotspot_victim_ip', src)
        self.assertIn('def _ics_apply_percent_cut_windivert', src)
        self.assertIn('def _ics_apply_advanced_shaping_windivert', src)
        toggle = src[src.index('def togglePercentCut'): src.index('def stopPercentCut')]
        self.assertIn('plan.is_ics_downstream', toggle)
        self.assertIn('_ics_apply_percent_cut_windivert(device, pct)', toggle)
        self.assertIn('def _ics_quiesce_killer_mitm', src)
        self.assertIn('_ics_quiesce_killer_mitm(device)', src)

    def test_passes_byte_ratio_matches_forwarder_semantics(self) -> None:
        budget = 0.0
        allowed = 0
        for _ in range(200):
            ok, budget = wd.IcsWinDivertLagGate._passes_byte_ratio(99, budget, 100)
            if ok:
                allowed += 1
        self.assertGreater(allowed, 150)
        self.assertLess(allowed, 200)
        ok2, _ = wd.IcsWinDivertLagGate._passes_byte_ratio(1, 0.0, 1000)
        self.assertFalse(ok2)

    def test_run_loop_passthrough_non_victim_before_impairment(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        idx = src.index('if not (from_v or to_v)')
        self.assertLess(idx, src.index('if impair_mode == IMPAIR_OFF'))

    def test_start_opens_single_handle_subnet_forward_first(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate.start)
        self.assertIn('_open_best_windivert_handle', src)
        self.assertIn('self._handles = [h]', src)
        self.assertNotIn('_open_ics_windivert_handles', src)
        open_src = inspect.getsource(wd._ics_windivert_open_candidates)
        self.assertIn('on_subnet', open_src)
        self.assertIn("_ics_clumsy_victim_filter(vip), 'victim'", open_src)
        best_src = inspect.getsource(wd._open_best_windivert_handle)
        self.assertIn(
            '(WINDIVERT_LAYER_NETWORK_FORWARD, WINDIVERT_LAYER_NETWORK)',
            best_src.replace('\n', ' '),
        )

    def test_open_candidates_subnet_only_when_victim_on_hotspot(self) -> None:
        off = wd._ics_windivert_open_candidates('192.168.1.50', '192.168.137.')
        self.assertEqual(len(off), 1)
        on = wd._ics_windivert_open_candidates('192.168.137.55', '192.168.137.')
        self.assertTrue(any('137.' in f for f, _ in on))

    def test_open_candidates_hotspot_capture_for_home_lan_table_ip(self) -> None:
        cands = wd._ics_windivert_open_candidates(
            '192.168.1.50', '192.168.137.', hotspot_capture=True
        )
        names = [d for _, d in cands]
        self.assertIn('forward', names)
        self.assertIn('broad', names)
        self.assertNotIn('victim', names)

    def test_open_candidates_ifidx_first_when_on_hotspot_subnet(self) -> None:
        with mock.patch('tools.clumsy_inline.clumsy_ics_downstream_ifidx', return_value=16):
            cands = wd._ics_windivert_open_candidates('192.168.137.55', '192.168.137.')
        self.assertGreaterEqual(len(cands), 4)
        self.assertEqual(cands[0][1], 'ifidx')
        self.assertIn('ifIdx == 16', cands[0][0])
        self.assertEqual(cands[-1][1], 'victim')

    def test_open_candidates_broad_before_victim_when_no_ifidx(self) -> None:
        with mock.patch('tools.clumsy_inline.clumsy_ics_downstream_ifidx', return_value=0):
            cands = wd._ics_windivert_open_candidates('192.168.137.55', '192.168.137.')
        names = [d for _, d in cands]
        self.assertIn('forward', names)
        self.assertIn('broad', names)
        self.assertEqual(names[-1], 'victim')
        self.assertLess(names.index('broad'), names.index('victim'))

    def test_pause_drops_unparsed_packets_when_blocking(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        block = src[src.index('if not parsed:'): src.index('src, dst = parsed')]
        self.assertIn('IMPAIR_PAUSE and blocking', block)
        self.assertIn('continue', block)

    def test_ipv4_parse_handles_ethernet_header(self) -> None:
        eth = bytes.fromhex(
            'ffffffffffff0011223344550800'
            '450000140000000000000000c0a889c208080808'
        )
        self.assertEqual(wd._parse_ipv4_src_dst(eth), ('192.168.137.194', '8.8.8.8'))

    def test_victim_packet_roles_no_broad_nat_fallback(self) -> None:
        from_v, to_v, _active = wd._victim_packet_roles(
            '73.12.1.2',
            '8.8.8.8',
            '192.168.1.50',
            '192.168.137.',
        )
        self.assertFalse(from_v)
        self.assertFalse(to_v)

    def test_victim_packet_roles_post_nat_uses_pinned_victim_only(self) -> None:
        from_v, to_v, active = wd._victim_packet_roles(
            '73.12.1.2',
            '8.8.8.8',
            '192.168.137.55',
            '192.168.137.',
            outbound=True,
            subnet_capture=True,
        )
        self.assertTrue(from_v)
        self.assertFalse(to_v)
        self.assertEqual(active, '192.168.137.55')

    def test_victim_packet_roles_post_nat_unknown_outbound_impairs(self) -> None:
        from_v, to_v, active = wd._victim_packet_roles(
            '73.12.1.2',
            '8.8.8.8',
            '192.168.137.55',
            '192.168.137.',
            outbound=None,
            subnet_capture=True,
        )
        self.assertTrue(from_v)
        self.assertTrue(to_v)
        self.assertEqual(active, '192.168.137.55')

    def test_victim_packet_roles_rejects_other_hotspot_client(self) -> None:
        from_v, to_v, _active = wd._victim_packet_roles(
            '192.168.137.56',
            '8.8.8.8',
            '192.168.137.55',
            '192.168.137.',
        )
        self.assertFalse(from_v)
        self.assertFalse(to_v)

    def test_victim_packet_roles_matches_pinned_ip_only(self) -> None:
        from_v, to_v, active = wd._victim_packet_roles(
            '192.168.137.55',
            '8.8.8.8',
            '192.168.137.55',
            '192.168.137.',
        )
        self.assertTrue(from_v)
        self.assertFalse(to_v)
        self.assertEqual(active, '192.168.137.55')

    def test_victim_packet_roles_skips_gateway(self) -> None:
        from_v, to_v, _active = wd._victim_packet_roles(
            '192.168.137.1',
            '8.8.8.8',
            '192.168.137.55',
            '192.168.137.',
        )
        self.assertFalse(from_v)
        self.assertFalse(to_v)

    def test_shaping_forwards_when_delay_zero(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        self.assertIn('if impair_mode == IMPAIR_SHAPE and (is_from_victim or is_to_victim)', src)
        self.assertIn('shape_delay > 0', src)
        self.assertIn('_send_immediate', src)

    def test_hotspot_sched_tick_uses_windivert_on_ics(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        tick = src[src.index('def _mitm_adv_apply_sched_tick'): src.index('def start_mitm_shaping_from_advanced')]
        self.assertIn('_uses_windivert(device)', tick)
        self.assertIn('_ics_apply_advanced_shaping_windivert', tick)

    def test_windivert_impostor_dropped_not_reshaped(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        block = src[src.index('if _windivert_addr_impostor'): src.index('parsed = _parse_ipv4_src_dst')]
        self.assertIn('continue', block)
        self.assertNotIn('_send_immediate', block)

    def test_open_handle_prefers_impostor_with_fallback(self) -> None:
        src = inspect.getsource(wd._open_windivert_handle)
        self.assertIn('_ics_windivert_filter_no_impostor', src)
        self.assertIn('for candidate in', src)

    def test_windivert_outbound_flag_uses_address_bitfield(self) -> None:
        # Outbound at bit 17 in UINT64 at offset 8.
        addr = bytearray(64)
        word = 1 << 17
        addr[8:16] = int(word).to_bytes(8, 'little')
        self.assertTrue(wd._windivert_addr_outbound(bytes(addr)))
        imp = bytearray(64)
        imp[8:16] = (1 << 19).to_bytes(8, 'little')
        self.assertTrue(wd._windivert_addr_impostor(bytes(imp)))

    def test_run_loop_does_not_retarget_pinned_victim(self) -> None:
        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        self.assertNotIn('self._victim = active', src)

    def test_flow_stable_pins_percent_cut_and_mitm_ips(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        fn = src[src.index('def _flow_stable_victim_ip'): src.index('def _ensure_ics_lag_gate')]
        self.assertIn('percent_cut_device_ip', fn)
        self.assertIn('mitm_shaping_device_ip', fn)


if __name__ == '__main__':
    unittest.main()
