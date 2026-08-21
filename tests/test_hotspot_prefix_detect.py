"""Hosted Network 192.168.173.x must be treated as a hotspot subnet."""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Import only the pure helpers — avoid get_ifaces_cached → scapy on wedged Npcap.
from tools.clumsy_inline import (  # noqa: E402
    _ICS_KNOWN_PREFIXES,
    _ipconfig_has_softap_gateway,
    _netsh_hostednetwork_started,
    _netsh_interface_has_softap_nic,
    ics_forwarding_must_stay_on,
    ics_prefix_for_ip,
    resolve_ics_downstream_prefix,
    victim_on_clumsy_ics_subnet,
)


class TestHotspotPrefixDetect(unittest.TestCase):
    def test_known_prefixes_include_hosted_network(self) -> None:
        self.assertIn('192.168.137.', _ICS_KNOWN_PREFIXES)
        self.assertIn('192.168.173.', _ICS_KNOWN_PREFIXES)

    def test_victim_on_173_subnet(self) -> None:
        self.assertTrue(victim_on_clumsy_ics_subnet('192.168.173.22'))
        self.assertTrue(victim_on_clumsy_ics_subnet('192.168.137.22'))
        self.assertFalse(victim_on_clumsy_ics_subnet('192.168.1.22'))

    def test_ics_forwarding_stays_on_for_live_hotspot(self) -> None:
        from tools import clumsy_inline as inline

        with patch.object(inline, 'clumsy_mode_enabled', return_value=False), patch.object(
            inline, 'windows_hotspot_session_live', return_value=True
        ):
            self.assertTrue(ics_forwarding_must_stay_on())
        with patch.object(inline, 'clumsy_mode_enabled', return_value=False), patch.object(
            inline, 'windows_hotspot_session_live', return_value=False
        ):
            self.assertFalse(ics_forwarding_must_stay_on())
        with patch.object(inline, 'clumsy_mode_enabled', return_value=True), patch.object(
            inline, 'windows_hotspot_session_live', return_value=False
        ):
            self.assertTrue(ics_forwarding_must_stay_on())

    def test_softap_text_parsers(self) -> None:
        self.assertTrue(_ipconfig_has_softap_gateway('IPv4 Address . . . 192.168.137.1'))
        self.assertTrue(_ipconfig_has_softap_gateway('192.168.173.1'))
        self.assertFalse(_ipconfig_has_softap_gateway('192.168.1.56'))
        self.assertTrue(
            _netsh_hostednetwork_started('Hosted network settings\n    Status                 : Started')
        )
        self.assertFalse(
            _netsh_hostednetwork_started('Hosted network settings\n    Status                 : Not started')
        )
        self.assertTrue(
            _netsh_interface_has_softap_nic(
                'Admin State    State          Type             Interface Name\n'
                'Enabled        Connected      Dedicated        Local Area Connection* 9'
            )
        )
        self.assertTrue(
            _netsh_interface_has_softap_nic(
                'Enabled        Connected      Dedicated        Microsoft Wi-Fi Direct Virtual Adapter'
            )
        )
        self.assertFalse(
            _netsh_interface_has_softap_nic(
                'Enabled        Connected      Dedicated        Wi-Fi\n'
                'Enabled        Disconnected   Dedicated        Local Area Connection* 2'
            )
        )

    def test_leftover_disconnected_direct_is_not_live_hotspot(self) -> None:
        from tools import clumsy_inline as inline

        class _Proc:
            stdout = 'Hosted network settings\n    Status                 : Not started'
            returncode = 0

        listing = (
            'Admin State    State          Type             Interface Name\n'
            'Enabled        Connected      Dedicated        Wi-Fi\n'
            'Enabled        Disconnected   Dedicated        Local Area Connection* 10'
        )
        with patch.object(inline.sys, 'platform', 'win32'), patch(
            'tools.utils.terminal', return_value=listing
        ), patch('tools.utils.run_command', return_value=_Proc()):
            self.assertFalse(inline.windows_hotspot_session_live())

    def test_connected_softap_is_live_hotspot(self) -> None:
        from tools import clumsy_inline as inline

        class _Proc:
            stdout = 'Hosted network settings\n    Status                 : Not started'
            returncode = 0

        listing = (
            'Admin State    State          Type             Interface Name\n'
            'Enabled        Connected      Dedicated        Local Area Connection* 10'
        )
        with patch.object(inline.sys, 'platform', 'win32'), patch(
            'tools.utils.terminal', return_value=listing
        ), patch('tools.utils.run_command', return_value=_Proc()):
            self.assertTrue(inline.windows_hotspot_session_live())

    def test_ics_prefix_for_ip(self) -> None:
        self.assertEqual(ics_prefix_for_ip('192.168.173.40'), '192.168.173.')
        self.assertEqual(ics_prefix_for_ip('192.168.137.40'), '192.168.137.')
        self.assertEqual(ics_prefix_for_ip('192.168.1.40'), '')

    def test_resolve_prefers_victim_over_state(self) -> None:
        with patch(
            'tools.clumsy_inline.clumsy_ics_downstream_prefix',
            return_value='192.168.137.',
        ):
            self.assertEqual(
                resolve_ics_downstream_prefix('192.168.173.22'),
                '192.168.173.',
            )

    def test_apply_router_context_uses_victim_prefix(self) -> None:
        from tools import clumsy_inline as inline

        scanner = type('S', (), {})()
        scanner.iface = type('I', (), {'mac': 'AA:BB:CC:DD:EE:FF'})()
        scanner.devices = []
        killer = type('K', (), {})()
        with patch.object(inline, 'clumsy_mode_enabled', return_value=True), patch.object(
            inline.sys, 'platform', 'win32'
        ), patch.object(
            inline, 'read_clumsy_ics_state', return_value={'downstream_prefix': '192.168.137.'}
        ), patch.object(
            inline, 'clumsy_ics_downstream_prefix', return_value='192.168.137.'
        ):
            ok = inline.apply_clumsy_ics_router_context(
                scanner, killer, '192.168.173.40'
            )
        self.assertTrue(ok)
        self.assertEqual(scanner.router_ip, '192.168.173.1')
        self.assertEqual(killer.router['ip'], '192.168.173.1')

    def test_downstream_prefix_live_wins_over_stale_state(self) -> None:
        from tools import clumsy_inline as inline
        from tools.clumsy_inline import clumsy_ics_downstream_prefix

        def _clear_cache() -> None:
            inline._LIVE_HOTSPOT_PREFIX_CACHE = ('', 0.0)
            inline._LIVE_HOTSPOT_PREFIX_REFRESHING = False

        # SoftAP off → use saved state.
        _clear_cache()
        with patch(
            'tools.clumsy_inline.read_clumsy_ics_state',
            return_value={'downstream_prefix': '192.168.173.'},
        ), patch(
            'tools.clumsy_inline._detect_live_hotspot_prefix',
            return_value='',
        ) as detect:
            self.assertEqual(clumsy_ics_downstream_prefix(), '192.168.173.')
            detect.assert_called()

        # SoftAP up → live wins even when state still says 137.
        _clear_cache()
        with patch(
            'tools.clumsy_inline.read_clumsy_ics_state',
            return_value={'downstream_prefix': '192.168.137.'},
        ), patch(
            'tools.clumsy_inline._detect_live_hotspot_prefix',
            return_value='192.168.173.',
        ):
            self.assertEqual(clumsy_ics_downstream_prefix(), '192.168.173.')

        _clear_cache()
        with patch(
            'tools.clumsy_inline.read_clumsy_ics_state',
            return_value={},
        ), patch(
            'tools.clumsy_inline._detect_live_hotspot_prefix',
            return_value='192.168.173.',
        ):
            self.assertEqual(clumsy_ics_downstream_prefix(), '192.168.173.')

        # Fresh negative cache must not re-block on netsh every call.
        inline._LIVE_HOTSPOT_PREFIX_CACHE = ('', time.monotonic())
        with patch(
            'tools.clumsy_inline.read_clumsy_ics_state',
            return_value={'downstream_prefix': '192.168.137.'},
        ), patch(
            'tools.clumsy_inline._detect_live_hotspot_prefix',
            return_value='192.168.173.',
        ) as detect:
            self.assertEqual(clumsy_ics_downstream_prefix(), '192.168.137.')
            detect.assert_not_called()

    def test_softap_ifidx_locale_address_headers(self) -> None:
        """French/Spanish netsh address headers must still resolve SoftAP ifIdx."""
        from tools import clumsy_inline as inline

        french = (
            'Configuration pour l\'interface "Connexion au réseau local* 12"\n'
            '    DHCP activé:                         Oui\n'
            '    Adresse IP:                           192.168.173.1\n'
            '    Masque de sous-réseau:                255.255.255.0\n'
        )
        spanish = (
            'Configuración para la interfaz "Conexión de área local* 3"\n'
            '    DHCP habilitado:                      Sí\n'
            '    Dirección IP:                         192.168.137.1\n'
            '    Máscara de subred:                    255.255.255.0\n'
        )
        listing = (
            'Idx     Met         MTU          State                Name\n'
            '16       25       1500          connected            Connexion au réseau local* 12\n'
            '17       25       1500          connected            Conexión de área local* 3\n'
        )

        class _Proc:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout
                self.returncode = 0

        # Clear cache between locales.
        if hasattr(inline.clumsy_ics_downstream_ifidx, '_cached_idx'):
            delattr(inline.clumsy_ics_downstream_ifidx, '_cached_idx')

        with patch.object(inline.sys, 'platform', 'win32'), patch(
            'tools.clumsy_inline.read_clumsy_ics_state', return_value={}
        ), patch(
            'tools.clumsy_inline.clumsy_ics_downstream_ifidx_from_arp', return_value=0
        ), patch(
            'tools.utils.run_command', return_value=_Proc(french)
        ), patch(
            'tools.utils.terminal', return_value=listing
        ):
            self.assertEqual(inline.clumsy_ics_downstream_ifidx(), 16)

        if hasattr(inline.clumsy_ics_downstream_ifidx, '_cached_idx'):
            delattr(inline.clumsy_ics_downstream_ifidx, '_cached_idx')

        with patch.object(inline.sys, 'platform', 'win32'), patch(
            'tools.clumsy_inline.read_clumsy_ics_state', return_value={}
        ), patch(
            'tools.clumsy_inline.clumsy_ics_downstream_ifidx_from_arp', return_value=0
        ), patch(
            'tools.utils.run_command', return_value=_Proc(spanish)
        ), patch(
            'tools.utils.terminal', return_value=listing
        ):
            self.assertEqual(inline.clumsy_ics_downstream_ifidx(), 17)

        # Do not leave SoftAP ifIdx cache stuck for later tests / app import.
        if hasattr(inline.clumsy_ics_downstream_ifidx, '_cached_idx'):
            delattr(inline.clumsy_ics_downstream_ifidx, '_cached_idx')


if __name__ == '__main__':
    unittest.main()
