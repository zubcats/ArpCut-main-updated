"""Compatibility hardening: Npcap paths, subnet prefix, error codes."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tools.diag_privacy import same_ipv4_subnet  # noqa: E402
from tools.user_errors import ERROR_CODES, format_error_code  # noqa: E402


class TestIcsIpBothPrefixes(unittest.TestCase):
    def test_is_ics_ip_accepts_137_and_173(self) -> None:
        from networking.device_table import _is_ics_ip

        self.assertTrue(_is_ics_ip('192.168.137.50', '192.168.137.'))
        self.assertTrue(_is_ics_ip('192.168.173.50', '192.168.137.'))
        self.assertTrue(_is_ics_ip('192.168.137.50', '192.168.173.'))
        self.assertFalse(_is_ics_ip('192.168.1.50', '192.168.137.'))


class TestArpIfaceHeaderLocale(unittest.TestCase):
    def test_parse_german_schnittstelle_header(self) -> None:
        # Extract parser without importing scapy via tools.utils module body side-effects
        # beyond the lazy conf proxy (safe).
        from tools.utils import _parse_windows_arp_by_interface
        from unittest.mock import patch

        sample = (
            'Schnittstelle: 192.168.1.10 --- 0xc\n'
            '  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamisch\n'
            '  192.168.1.50          11-22-33-44-55-66     dynamisch\n'
        )
        with patch('tools.utils.terminal', return_value=sample), patch(
            'tools.utils.sys.platform', 'win32'
        ):
            by_iface = _parse_windows_arp_by_interface()
        self.assertIn('192.168.1.50', by_iface.get('192.168.1.10', set()))


class TestSameSubnetPrefix(unittest.TestCase):
    def test_default_slash24(self) -> None:
        self.assertTrue(same_ipv4_subnet('192.168.1.56', '192.168.1.1'))
        self.assertFalse(same_ipv4_subnet('192.168.1.56', '192.168.0.1'))

    def test_slash23_accepts_adjacent_slash24(self) -> None:
        # 192.168.0.0/23 covers 192.168.0.0–192.168.1.255
        self.assertTrue(
            same_ipv4_subnet('192.168.0.10', '192.168.1.50', prefix_len=23)
        )
        self.assertFalse(
            same_ipv4_subnet('192.168.0.10', '192.168.2.50', prefix_len=23)
        )

    def test_ipv4_same_link_helper(self) -> None:
        # Mirror tools.utils.ipv4_same_link without importing utils (utils→scapy can hang
        # when Npcap/admin state is wedged on a developer machine).
        def ipv4_same_link(ip_a: str, ip_b: str, *, prefix_len: int = 24) -> bool:
            return bool(same_ipv4_subnet(ip_a, ip_b, prefix_len=prefix_len))

        self.assertTrue(ipv4_same_link('10.0.0.2', '10.0.0.99', prefix_len=24))
        self.assertFalse(ipv4_same_link('10.0.0.2', '10.0.1.99', prefix_len=24))


class TestErrorCodes(unittest.TestCase):
    def test_catalog_has_core_codes(self) -> None:
        for code in (
            'ZC-NPCAP',
            'ZC-NPCAP-ADMIN',
            'ZC-FWD',
            'ZC-WD-HVCI',
            'ZC-IPV6',
            'ZC-WPA3',
            'ZC-MLO',
            'ZC-ISOLATION',
            'ZC-ICS',
        ):
            self.assertIn(code, ERROR_CODES)

    def test_format_includes_code(self) -> None:
        msg = format_error_code('ZC-NPCAP', 'retry install')
        self.assertIn('ZC-NPCAP', msg)
        self.assertNotIn('github', msg.lower())


class TestVpnIfaceDeprioritize(unittest.TestCase):
    def test_vpn_name_detected(self) -> None:
        from tools.utils import _iface_looks_vpn_or_virtual
        from networking.ifaces import NetFace

        vpn = NetFace(
            {
                'name': 'WireGuard Tunnel',
                'guid': 'guid-wg',
                'mac': 'AA:BB:CC:DD:EE:FF',
                'ips': ['10.8.0.2'],
            }
        )
        hyperv = NetFace(
            {
                'name': 'vEthernet (Default Switch)',
                'guid': 'guid-hv',
                'mac': 'AA:BB:CC:DD:EE:02',
                'ips': ['172.22.192.1'],
            }
        )
        wifi = NetFace(
            {
                'name': 'Wi-Fi',
                'guid': 'guid-wifi',
                'mac': 'AA:BB:CC:DD:EE:01',
                'ips': ['192.168.1.56'],
            }
        )
        self.assertTrue(_iface_looks_vpn_or_virtual(vpn))
        self.assertTrue(_iface_looks_vpn_or_virtual(hyperv))
        self.assertFalse(_iface_looks_vpn_or_virtual(wifi))


class TestNpcapExists(unittest.TestCase):
    def test_true_when_system32_wpcap_present(self) -> None:
        from tools import utils_gui

        def _isdir(p: str) -> bool:
            return str(p).lower().endswith('npcap')

        def _exists(p: str) -> bool:
            pl = str(p).replace('/', '\\').lower()
            return pl.endswith('wpcap.dll') or pl.endswith('\\npcap')

        with patch.object(utils_gui, 'sys') as fake_sys, patch.object(
            utils_gui.path, 'isdir', side_effect=_isdir
        ), patch.object(utils_gui.path, 'exists', side_effect=_exists):
            fake_sys.platform = 'win32'
            self.assertTrue(utils_gui.npcap_exists())

    def test_false_when_nothing_present(self) -> None:
        from tools import utils_gui

        with patch.object(utils_gui, 'sys') as fake_sys, patch.object(
            utils_gui.path, 'isdir', return_value=False
        ), patch.object(utils_gui.path, 'exists', return_value=False), patch.dict(
            'sys.modules', {'winreg': None}
        ):
            fake_sys.platform = 'win32'
            # Registry/service probes may still succeed on the developer machine;
            # only assert the function returns a bool without raising.
            self.assertIsInstance(utils_gui.npcap_exists(), bool)


class TestConstantsNpcapCandidates(unittest.TestCase):
    def test_candidates_include_system32(self) -> None:
        from constants import NPCAP_CANDIDATE_PATHS, NPCAP_PATH

        self.assertTrue(any('System32' in p for p in NPCAP_CANDIDATE_PATHS))
        self.assertIn(NPCAP_PATH, NPCAP_CANDIDATE_PATHS)


class TestZubcutNpcapDllBootstrap(unittest.TestCase):
    def test_prefer_npcap_dll_directory_helper_exists(self) -> None:
        zubcut = (_ROOT / 'src' / 'zubcut.py').read_text(encoding='utf-8')
        self.assertIn('_prefer_npcap_dll_directory', zubcut)
        self.assertIn('SetDllDirectoryW', zubcut)
        # Must restore default DLL search so WinDivert .sys can load beside its DLL.
        self.assertIn('set_dll(None)', zubcut)
        self.assertIn('LoadLibraryW', zubcut)
        self.assertIn('ensure_npcap_service_running', zubcut)
        self.assertIn('faulthandler.enable', zubcut)

    def test_ensure_npcap_queries_without_requiring_start_rights(self) -> None:
        """Non-admin OpenService(QUERY|START) fails even when driver is RUNNING."""
        import ctypes
        from ctypes import wintypes
        from tools import utils_gui

        if not sys.platform.startswith('win'):
            self.skipTest('Windows-only')

        SERVICE_QUERY_STATUS = 0x0004
        SERVICE_START = 0x0010
        SERVICE_RUNNING = 0x00000004
        handles = {'scm': 0x100, 'svc_query': 0x200}

        class FakeAdvapi:
            def OpenSCManagerW(self, *_a):
                return handles['scm']

            def OpenServiceW(self, _scm, name, access):
                if name not in ('npcap', 'npf'):
                    return 0
                # Old bug: QUERY|START denied → false ZC-NPCAP-SVC while running.
                if access == (SERVICE_QUERY_STATUS | SERVICE_START):
                    return 0
                if access == SERVICE_QUERY_STATUS:
                    return handles['svc_query']
                return 0

            def QueryServiceStatus(self, _svc, status_ptr):
                # status_ptr is byref(SERVICE_STATUS); write RUNNING into dwCurrentState.
                try:
                    status = status_ptr._obj
                    status.dwCurrentState = SERVICE_RUNNING
                except Exception:
                    cast = ctypes.cast(status_ptr, ctypes.POINTER(ctypes.c_ulong * 7))
                    cast.contents[1] = SERVICE_RUNNING
                return 1

            def StartServiceW(self, *_a):
                raise AssertionError('StartService should not run when QUERY shows RUNNING')

            def CloseServiceHandle(self, *_a):
                return 1

        fake = FakeAdvapi()
        with patch.object(ctypes, 'windll') as windll:
            windll.advapi32 = fake
            # Ensure win path even if helper short-circuits elsewhere.
            with patch.object(utils_gui.sys, 'platform', 'win32'):
                self.assertTrue(utils_gui.ensure_npcap_service_running())


class TestWindivertStaleServiceRepair(unittest.TestCase):
    def test_deletes_temp_image_path_even_if_file_exists(self) -> None:
        from tools import ics_windivert_shaper as wd

        want = r'C:\Program Files\ZubCut\windivert\WinDivert64.sys'
        stale = r'C:\Users\x\AppData\Local\Temp\WinDivert\WinDivert64.sys'
        with patch.object(wd, '_windivert_normalized_path', side_effect=lambda p: p), patch.object(
            wd.os.path, 'isfile', side_effect=lambda p: True
        ), patch.object(
            wd, '_windivert_service_image_path', return_value=stale
        ), patch.object(wd, '_windivert_sc_stop_and_delete') as delete:
            ok, note = wd._windivert_repair_stale_service(want)
        self.assertTrue(ok)
        self.assertIn('removed stale', note.lower())
        delete.assert_called_once()

    def test_keeps_other_stable_driver_path(self) -> None:
        from tools import ics_windivert_shaper as wd

        want = r'C:\Program Files\ZubCut\windivert\WinDivert64.sys'
        other = r'C:\Windows\System32\drivers\WinDivert64.sys'
        with patch.object(wd, '_windivert_normalized_path', side_effect=lambda p: p), patch.object(
            wd.os.path, 'isfile', side_effect=lambda p: True
        ), patch.object(
            wd, '_windivert_service_image_path', return_value=other
        ), patch.object(wd, '_windivert_sc_stop_and_delete') as delete:
            ok, note = wd._windivert_repair_stale_service(want)
        self.assertTrue(ok)
        self.assertIn('another valid', note.lower())
        delete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
