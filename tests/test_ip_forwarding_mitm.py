"""Windows IP forwarding must stay off while MITM victims are armed."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestIpForwardingMitm(unittest.TestCase):
    def test_stop_forwarder_does_not_enable_while_victims_armed(self) -> None:
        from networking.killer import Killer

        k = Killer.__new__(Killer)
        k.forwarders = {}
        k.killed = {'AA:BB:CC:DD:EE:FF': {'mac': 'AA:BB:CC:DD:EE:FF', 'ip': '192.168.1.165'}}
        with mock.patch('networking.killer.enable_ip_forwarding') as enable:
            k._stop_forwarder('AA:BB:CC:DD:EE:FF')
        enable.assert_not_called()

    def test_stop_forwarder_keeps_forwarding_off_when_idle(self) -> None:
        from networking.killer import Killer

        k = Killer.__new__(Killer)
        k.forwarders = {}
        k.killed = {}
        with (
            mock.patch('networking.killer.enable_ip_forwarding') as enable,
            mock.patch('networking.killer.disable_ip_forwarding') as disable,
            mock.patch(
                'tools.clumsy_inline.ics_forwarding_must_stay_on',
                return_value=False,
            ),
        ):
            k._stop_forwarder('AA:BB:CC:DD:EE:FF')
        enable.assert_not_called()
        disable.assert_called_once()

    def test_stop_forwarder_skips_disable_in_clumsy_mode(self) -> None:
        from networking.killer import Killer

        k = Killer.__new__(Killer)
        k.forwarders = {}
        k.killed = {}
        with (
            mock.patch('networking.killer.disable_ip_forwarding') as disable,
            mock.patch(
                'tools.clumsy_inline.ics_forwarding_must_stay_on',
                return_value=True,
            ),
        ):
            k._stop_forwarder('AA:BB:CC:DD:EE:FF')
        disable.assert_not_called()

    def test_kill_disables_forwarding_on_lan_path(self) -> None:
        from networking.killer import Killer

        k = Killer.__new__(Killer)
        k.iface = type('I', (), {'name': 'Wi-Fi', 'guid': '\\Device\\NPF_test', 'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.168.1.56'})()
        k.router = {'ip': '192.168.1.1', 'mac': '11:22:33:44:55:66'}
        k.killed = {}
        k.forwarders = {}
        k._op_seq = {}
        victim = {'mac': 'AA:BB:CC:DD:EE:FF', 'ip': '192.168.1.165'}
        with (
            mock.patch.object(Killer, '_sync_iface_for_victim'),
            mock.patch.object(Killer, '_refresh_victim_mac_from_cache'),
            mock.patch.object(Killer, '_next_op_seq', return_value=1),
            mock.patch.object(Killer, '_stop_forwarder'),
            mock.patch.object(Killer, '_poison_arp_now'),
            mock.patch.object(Killer, '_kill_arp_worker'),
            mock.patch.object(Killer, '_apply_traffic_cut_sync', return_value=False),
            mock.patch.object(Killer, '_reinforce_full_cut_async'),
            mock.patch('networking.killer.disable_ip_forwarding') as disable,
        ):
            Killer.kill(k, victim, wait_after=0, traffic_cut=True, ics_mode=False)
        disable.assert_called_once()

    def test_set_windows_ip_forwarding_uses_per_iface_not_global_netsh(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('def _set_windows_ip_forwarding', src)
        self.assertIn("f'forwarding={flag}'", src)
        self.assertIn('def _iface_indexes_from_netsh', src)
        # Kill must not block on PowerShell; PS is fallback only.
        self.assertIn('blocking: bool = False', src)
        self.assertIn("name='zubcut-ip-forwarding'", src)
        # Old invalid global netsh command must not come back (silent no-op → leaky Kill).
        self.assertNotIn("'set', 'global', 'forwarding=", src)
        self.assertNotIn('["netsh", "interface", "ipv4", "set", "global"', src)

    def test_startup_disable_is_blocking(self) -> None:
        path = os.path.join(_SRC, 'tools', 'windows_network_tune.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        block = src[
            src.index('def ensure_home_lan_mitm_forwarding_off') : src.index(
                'def _apply_intel_ethernet_low_latency'
            )
        ]
        self.assertIn('disable_ip_forwarding(blocking=True)', block)
        self.assertIn('ics_forwarding_must_stay_on', block)

    def test_iface_indexes_from_netsh_parses_idx(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        ns: dict = {}
        chunk = src[
            src.index('def _iface_indexes_from_netsh') : src.index(
                'def _apply_windows_ip_forwarding_ifaces'
            )
        ]
        exec(chunk, ns)  # noqa: S102
        sample = (
            'Idx     Met         MTU          State                Name\n'
            '---  ----------  ----------  ------------  ---------------------------\n'
            '  1          75  4294967295  connected     Loopback Pseudo-Interface 1\n'
            ' 12          25        1500  connected     Wi-Fi\n'
            '  5          25        1500  disconnected  Ethernet\n'
        )
        self.assertEqual(ns['_iface_indexes_from_netsh'](sample), ['1', '12', '5'])
        self.assertEqual(
            ns['_priority_iface_keys']('Wi-Fi', sample),
            ['Wi-Fi', '12'],
        )

    def test_kill_passes_priority_iface_to_disable(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        # Call sites may wrap kwargs across lines:
        #   disable_ip_forwarding(
        #       priority_iface=getattr(...),
        self.assertIn('disable_ip_forwarding(', src)
        self.assertIn('priority_iface=', src)
        self.assertIn('priority_iface: str | None = None', src)
        self.assertRegex(
            src,
            r'disable_ip_forwarding\(\s*(?:\n\s*)?priority_iface=',
        )

    def test_kill_disables_forwarding_after_instant_cut(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        kill = src[src.index('def kill(') : src.index('def _apply_traffic_cut_sync')]
        poison_at = kill.index('_poison_arp_now')
        cut_at = kill.index('_apply_traffic_cut_sync')
        disable_at = kill.index('disable_ip_forwarding')
        reinforce_at = kill.index('_reinforce_full_cut_async')
        self.assertLess(poison_at, cut_at)
        self.assertLess(cut_at, disable_at)
        self.assertLess(disable_at, reinforce_at)
        # Cut path must not re-ping (GUI already validated).
        apply = src[
            src.index('def _apply_traffic_cut_sync') : src.index('def apply_traffic_cut')
        ]
        self.assertNotIn('mitm_prereqs_ok', apply)

    def test_startup_does_not_reenable_forwarding_after_clean(self) -> None:
        path = os.path.join(_SRC, 'zubcut.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        # Startup cleans forwarding off; post-init must not turn it back on.
        self.assertIn('_ensure_clean_network_on_startup', src)
        block = src[src.index('GUI.scanner.init()') : src.index('reconcile_scanner_with_settings_iface')]
        self.assertNotIn('enable_ip_forwarding', block)

    def test_lan_warm_skips_forwarding_disable_when_hotspot_live(self) -> None:
        path = os.path.join(_SRC, 'gui', 'impairment_mitm.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        block = src[src.index('def _warm_lan_mitm_stack') : src.index('def _schedule_lan_ipv6_probe')]
        self.assertIn('ics_forwarding_must_stay_on', block)

    def test_killer_init_does_not_enable_forwarding(self) -> None:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        init = src[src.index('def __init__(self, router=DUMMY_ROUTER)') : src.index('def _next_op_seq')]
        self.assertNotIn('enable_ip_forwarding()', init)
