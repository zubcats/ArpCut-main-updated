"""Clumzy/ICS leftovers: ZubCut must not configure Windows sharing or hotspot."""

from __future__ import annotations

import inspect
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _gui_source import load_main_window_source, methods_through, method_src

from tools import clumsy_ics as ics
from tools import clumsy_inline as inline


class ClumsyHotspotSafetyTests(unittest.TestCase):
    def test_purge_stale_attack_blocks_does_not_raise(self) -> None:
        # Regression ZC-KPU5PP: purge used sys without importing it.
        result = ics.purge_clumsy_stale_attack_blocks()
        self.assertIsInstance(result, dict)
        self.assertIn('firewall_rules_removed', result)

    def test_purge_for_clumsy_enable_skips_full_teardown(self) -> None:
        from unittest.mock import patch

        with patch.object(ics, 'sys') as mock_sys:
            mock_sys.platform = 'win32'
            with patch('tools.pfctl.teardown_all_zubcut_network_attacks') as teardown:
                ics.purge_clumsy_stale_attack_blocks(for_clumsy_enable=True)
        teardown.assert_not_called()

    def test_legacy_ics_mutators_are_noops(self) -> None:
        banned = (
            'HNetShare',
            'EnableSharing',
            'DisableSharing',
            'hostednetwork',
            'Remove-NetIPAddress',
            'Start-Service',
            'SharedAccess',
            'icssvc',
        )
        for name in (
            'ensure_clumsy_ics_enabled',
            'repair_clumsy_network_sharing',
            'prepare_pc_mobile_hotspot',
            'clear_stale_softap_when_tethering_off',
            'rollback_clumsy_ics',
            'maybe_repair_stale_clumsy_ics_on_startup',
            'maybe_ensure_wlan_autoconfig_on_startup',
            'ensure_wlan_autoconfig_healthy',
        ):
            src = inspect.getsource(getattr(ics, name))
            for token in banned:
                self.assertNotIn(token, src, f'{name} still mentions {token}')
        self.assertEqual(ics.ensure_clumsy_ics_enabled()[0], True)
        self.assertEqual(ics.repair_clumsy_network_sharing()[0], True)
        self.assertEqual(ics.clear_stale_softap_when_tethering_off()[0], True)
        self.assertIsNone(ics.maybe_repair_stale_clumsy_ics_on_startup())
        self.assertFalse(hasattr(ics, '_PS_HOTSPOT_HELPERS'))
        self.assertFalse(hasattr(ics, '_ensure_clumsy_ics_enabled_impl'))

    def test_settings_and_startup_never_prep_ics(self) -> None:
        settings = os.path.join(_ROOT, 'src', 'gui', 'settings.py')
        zubcut = os.path.join(_SRC, 'zubcut.py')
        with open(settings, encoding='utf-8') as f:
            st = f.read()
        with open(zubcut, encoding='utf-8') as f:
            boot = f.read()
        self.assertNotIn('_ClumsyIcsPrepThread', st)
        self.assertNotIn('_begin_clumsy_mode_toggle', st)
        self.assertNotIn('ensure_clumsy_ics_enabled', st)
        self.assertNotIn('repair_clumsy_network_sharing', st)
        self.assertNotIn('Restoring network sharing', st)
        self.assertNotIn('maybe_ensure_wlan_autoconfig_on_startup', boot)
        self.assertNotIn('maybe_repair_stale_clumsy_ics_on_startup', boot)
        self.assertIn('reset_clumsy_mode_on_startup', boot)
        self.assertNotIn('net start SharedAccess', inspect.getsource(inline.maybe_prepare_ics))
        self.assertNotIn('terminal(', inspect.getsource(inline.maybe_prepare_ics))

    def test_format_clumsy_ics_error_not_duplicated(self) -> None:
        raw = 'Turn ON Mobile Hotspot in Windows Settings first.'
        once = ics.format_clumsy_ics_error(raw, topology='hotspot')
        twice = ics.format_clumsy_ics_error(once, topology='hotspot')
        self.assertEqual(once, twice)
        self.assertEqual(once.count('Valid hotspot path for Clumsy mode'), 1)
        self.assertIn('console on PC hotspot', once)
        self.assertIn('does not enable or repair Windows Internet sharing', once)

    def test_clumsy_hotspot_session_active_resolves_topology(self) -> None:
        """Regression ZC-4VZ0ZQ: read_clumsy_topology must be imported in clumsy_inline."""
        from unittest.mock import patch

        with patch.object(inline, 'clumsy_mode_enabled', return_value=False):
            self.assertFalse(inline.clumsy_hotspot_session_active())
        # Patch the name bound in clumsy_inline (from-import), not clumsy_ics.
        # Force win32 so non-Windows hosts (e.g. local agents) still exercise the path.
        with patch.object(inline, 'clumsy_mode_enabled', return_value=True), patch.object(
            inline, 'read_clumsy_topology', return_value='hotspot'
        ), patch.object(inline.sys, 'platform', 'win32'):
            self.assertTrue(inline.clumsy_hotspot_session_active())

    def test_clumsy_ics_subnet_and_gateway(self) -> None:
        path = ics.clumsy_ics_state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        had = os.path.isfile(path)
        old = None
        try:
            if had:
                with open(path, encoding='utf-8') as f:
                    old = f.read()
            with open(path, 'w', encoding='utf-8') as f:
                f.write(
                    '{"downstream_prefix":"192.168.137.","downstream_ipv4":"192.168.137.1"}'
                )
            self.assertTrue(inline.victim_on_clumsy_ics_subnet('192.168.137.50'))
            self.assertFalse(inline.victim_on_clumsy_ics_subnet('192.168.1.50'))
            # SoftAP off → state; live SoftAP would override (tested in test_hotspot_prefix_detect).
            from unittest.mock import patch

            with patch.object(inline, '_detect_live_hotspot_prefix', return_value=''):
                self.assertEqual(inline.clumsy_ics_downstream_prefix(), '192.168.137.')
        finally:
            if old is not None:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(old)
            elif not had and os.path.isfile(path):
                os.remove(path)

    def test_windivert_gate_keeps_recv_loop_on_idle(self) -> None:
        from tools import ics_windivert_shaper as wd

        src = inspect.getsource(wd.IcsWinDivertLagGate._run_loop)
        self.assertIn('ERROR_NO_DATA', src)
        self.assertIn('continue', src)
        self.assertNotRegex(
            src,
            r'if err == ERROR_NO_DATA:\s*\n\s*break',
        )

    def test_clumsy_ics_block_prefers_windivert_over_arp(self) -> None:
        self.assertIn('release_ics_victim_block', inline.__dict__)
        self.assertIn('IcsWinDivertLagGate', inspect.getsource(
            __import__('tools.ics_windivert_shaper', fromlist=['IcsWinDivertLagGate'])
        ))
        src = load_main_window_source()
        self.assertIn('def _apply_ics_client_block', src)
        self.assertIn('release_ics_victim_block', src)
        ics_block = methods_through('_apply_ics_client_block', '_clear_ics_client_block')
        self.assertIn('_ensure_ics_lag_gate', ics_block)
        self.assertTrue(
            'pause_connection' in ics_block or 'set_blocking(' in ics_block,
            'ICS block must use WinDivert pause, not ARP MITM',
        )
        wd_mod = __import__('tools.ics_windivert_shaper', fromlist=['IcsWinDivertLagGate'])
        gate_src = inspect.getsource(wd_mod.IcsWinDivertLagGate)
        wd_src = inspect.getsource(wd_mod)
        self.assertIn('prepare_stop', gate_src)
        self.assertIn('_discard_heap', gate_src)
        self.assertIn('_hold_pause', gate_src)
        self.assertIn('_PAUSE_HOLD_DUE', gate_src)
        self.assertIn('WINDIVERT_LAYER_NETWORK_FORWARD', wd_src)
        self.assertIn('192.168.137.', wd_src)
        self.assertIn('WINDIVERT_LAYER_NETWORK', wd_src)
        self.assertNotIn('stack_arp', ics_block)
        self.assertNotIn('apply_ics_victim_arp_block', ics_block)
        self.assertNotIn('_bg_block_ip', ics_block)
        self.assertNotIn('bool(block_ip', ics_block)
        self.assertNotIn('from tools.pfctl import block_ip', ics_block)
        arp_src = inspect.getsource(inline.apply_ics_victim_arp_block)
        self.assertIn('sync_scanner_iface_for_ics_downstream', arp_src)
        self.assertNotIn('sync_iface_for_victim_ip', arp_src)
        layers_src = inspect.getsource(wd_mod._layers_for_capture_desc)
        self.assertIn(
            '(WINDIVERT_LAYER_NETWORK_FORWARD, WINDIVERT_LAYER_NETWORK)',
            layers_src.replace('\n', ' '),
        )
        self.assertIn('_ics_windivert_filter', wd_src)
        start_src = gate_src[gate_src.index('def start'): gate_src.index('def set_blocking')]
        self.assertIn('_open_windivert_handles', start_src)
        self.assertIn('self._handles = [h for h', start_src)
        self.assertIn('_ics_windivert_filter', wd_src)
        killer_py = os.path.join(_SRC, 'networking', 'killer.py')
        with open(killer_py, encoding='utf-8') as f:
            ksrc = f.read()
        self.assertIn('ics_mode=False', ksrc)
        self.assertIn('refresh_router=not ics_mode', ksrc)

    def test_ensure_network_skips_arp_flush_in_clumsy_mode(self) -> None:
        src = load_main_window_source()
        # flush_arp must NOT be called from _ensure_network_context_for_victim:
        # it wipes the local ARP cache the next Kill ON depends on for fast
        # get_gateway_mac lookups (scapy.getmacbyip fallback = ~4 s timeout).
        self.assertNotIn('self.scanner.flush_arp()', src)
        # Clumsy ICS router context binding must still be guarded.
        self.assertIn('clumsy_mode_enabled()', src)
        self.assertIn('apply_clumsy_ics_router_context', src)

    def test_read_clumsy_topology_from_state_file(self) -> None:
        path = ics.clumsy_ics_state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        had = os.path.isfile(path)
        old = None
        try:
            if had:
                with open(path, encoding='utf-8') as f:
                    old = f.read()
            with open(path, 'w', encoding='utf-8') as f:
                f.write('{"topology":"ethernet"}')
            self.assertEqual(ics.read_clumsy_topology(), 'ethernet')
        finally:
            if old is not None:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(old)
            elif not had and os.path.isfile(path):
                os.remove(path)

    def test_startup_does_not_heal_wlan_or_ics(self) -> None:
        zubcut = os.path.join(_SRC, 'zubcut.py')
        with open(zubcut, encoding='utf-8') as f:
            src = f.read()
        self.assertNotIn('maybe_ensure_wlan_autoconfig_on_startup', src)
        self.assertIn('reset_clumsy_mode_on_startup', src)

    def test_reset_clumsy_mode_on_startup_keeps_setting(self) -> None:
        from unittest.mock import patch

        with patch.object(ics.os, 'name', 'nt'), patch(
            'tools.clumsy_ics.consume_clumsy_settings_restart_pending',
            return_value=False,
        ), patch(
            'tools.utils_gui.import_settings_as_dict',
            return_value={'clumsy_mode': True, 'clumsy_persist_across_restart': False},
        ), patch('tools.utils_gui.set_settings_many') as sm:
            ics.reset_clumsy_mode_on_startup()
        sm.assert_not_called()

    def test_reset_clumsy_mode_skips_when_restart_marker_present(self) -> None:
        from unittest.mock import patch

        with patch.object(ics.os, 'name', 'nt'), patch(
            'tools.clumsy_ics.consume_clumsy_settings_restart_pending',
            return_value=True,
        ), patch(
            'tools.utils_gui.import_settings_as_dict',
            return_value={'clumsy_mode': True, 'clumsy_persist_across_restart': False},
        ), patch('tools.utils_gui.set_settings_many') as sm:
            ics.reset_clumsy_mode_on_startup()
        sm.assert_not_called()

    def test_reset_clumsy_mode_skips_when_persist_flag_set(self) -> None:
        from unittest.mock import patch

        with patch.object(ics.os, 'name', 'nt'), patch(
            'tools.clumsy_ics.consume_clumsy_settings_restart_pending',
            return_value=False,
        ), patch(
            'tools.utils_gui.import_settings_as_dict',
            return_value={'clumsy_mode': True, 'clumsy_persist_across_restart': True},
        ), patch('tools.utils_gui.set_settings_many') as sm:
            ics.reset_clumsy_mode_on_startup()
        sm.assert_called_once_with({'clumsy_persist_across_restart': False})

    def test_maybe_repair_does_not_clear_softap_or_sharing(self) -> None:
        from unittest.mock import patch

        with patch.object(ics, 'clear_stale_softap_when_tethering_off') as clear, patch.object(
            ics, 'repair_clumsy_network_sharing'
        ) as repair:
            ics.maybe_repair_stale_clumsy_ics_on_startup()
        clear.assert_not_called()
        repair.assert_not_called()

    def test_flush_arp_skips_on_hotspot_subnet(self) -> None:
        from unittest.mock import MagicMock, patch

        from networking.scanner import Scanner

        sc = Scanner()
        sc.my_ip = '192.168.137.1'
        with patch('tools.clumsy_inline.hotspot_arp_cache_sensitive', return_value=True):
            with patch('networking.scanner.terminal') as term:
                sc.flush_arp()
        term.assert_not_called()

    def test_startup_teardown_does_not_clear_killed_before_unkill(self) -> None:
        src = load_main_window_source()
        block = src.split('def _ensure_clean_network_on_startup', 1)[1].split('\n    def ', 1)[0]
        self.assertNotIn('self.killer.killed.clear()', block)
        self.assertNotIn('heal_all_hotspot_arp_clients', block)
        self.assertNotIn('clear_stale_softap_when_tethering_off', block)

    def test_hotspot_heal_binds_softap_iface(self) -> None:
        heal = inspect.getsource(inline.heal_all_hotspot_arp_clients)
        apply = inspect.getsource(inline.apply_clumsy_ics_router_context)
        self.assertIn('sync_scanner_iface_for_ics_downstream', heal)
        self.assertIn('sync_scanner_iface_for_ics_downstream', apply)

    def test_unkill_all_uses_ics_router_context(self) -> None:
        from networking.killer import Killer

        src = inspect.getsource(Killer.unkill_all)
        self.assertIn('apply_clumsy_ics_router_context', src)
        self.assertIn('ics_mode=True', src)
        self.assertIn('heal_ics_client_after_mitm', src)

    def test_parse_ics_arp_entries(self) -> None:
        text = (
            'Interface: 192.168.137.1 --- 0x15\n'
            '  192.168.137.2          ab-cd-ef-12-34-56     dynamic\n'
            '  192.168.1.50           11-22-33-44-55-66     dynamic\n'
        )
        rows = inline._parse_ics_arp_entries(
            text,
            '192.168.137.1',
            '192.168.137.1',
            '192.168.137.',
            '192.168.137.1',
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ip'], '192.168.137.2')
        self.assertEqual(rows[0]['mac'], 'AB:CD:EF:12:34:56')

    def test_kill_all_requires_hotspot_block_success_before_marking_killed(self) -> None:
        src = method_src('killAll')
        self.assertIn("if self._apply_victim_block(prepared, 'both'):", src)
        self.assertIn('self._set_killed_profile(prepared, True)', src)
        fail_before_mark = src.split('self._set_killed_profile(prepared, True)', 1)[0]
        self.assertIn('if self._apply_victim_block', fail_before_mark)
        self.assertIn('Kill All failed', src)
        self.assertIn('failed_n', src)


if __name__ == '__main__':
    unittest.main()
