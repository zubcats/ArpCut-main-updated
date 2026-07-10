"""Npcap L2 socket prewarm and multi-token bind."""
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


class TestNpcapPrewarm(unittest.TestCase):
    @staticmethod
    def _killer_py() -> str:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def _main_py(self) -> str:
        return load_main_window_source()

    def test_get_socket_tries_npcap_tokens(self) -> None:
        src = self._killer_py()
        fn = src[src.index('def _get_socket'): src.index('def _send_packet')]
        self.assertIn('_iface_l2_tokens', fn)
        self.assertIn('for tok in self._iface_l2_tokens()', fn)

    def test_prewarm_l2_socket_exists(self) -> None:
        src = self._killer_py()
        self.assertIn('def prewarm_l2_socket', src)
        self.assertIn('def l2_socket_ready', src)

    def test_poison_waits_briefly_for_cold_socket(self) -> None:
        src = self._killer_py()
        poison = src[src.index('def _poison_arp_now'): src.index('def _poison_arp_now_async')]
        self.assertIn('prewarm_l2_socket(join_ms=120)', poison)

    def test_main_schedules_npcap_prewarm(self) -> None:
        src = self._main_py()
        self.assertIn('def _schedule_npcap_prewarm', src)
        self.assertIn("_schedule_npcap_prewarm('startup')", src)
        self.assertIn("_schedule_npcap_prewarm('select')", src)
        self.assertIn('schedule_windows_capture_maintenance', src)
        clicked = methods_through('deviceClicked', '_updateLagSwitchButtonState')
        self.assertIn("_schedule_npcap_prewarm('select')", clicked)

    def test_windows_network_tune_module(self) -> None:
        path = os.path.join(_SRC, 'tools', 'windows_network_tune.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('def maintain_windows_capture_stack', src)
        self.assertIn('def ensure_home_lan_mitm_forwarding_off', src)
        self.assertIn('INSECURE_NPCAP', src)
        self.assertIn('Win10Pcap', src)
        self.assertIn('AllowComputerToTurnOffDevice', src)
        self.assertIn('I219|Ethernet Connection', src)
        self.assertIn('PnPCapabilities', src)

    def test_startup_clears_ip_forwarding(self) -> None:
        src = self._main_py()
        block = methods_through('_ensure_clean_network_on_startup', 'quit_all')
        self.assertIn('ensure_home_lan_mitm_forwarding_off', block)

    def test_zubcut_post_init_maintain(self) -> None:
        path = os.path.join(_ROOT, 'src', 'zubcut.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn("_schedule_npcap_prewarm('post_init')", src)

    def test_settings_apply_prewarms_npcap(self) -> None:
        path = os.path.join(_SRC, 'gui', 'settings.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        apply = src[src.index('def apply_app_settings'): src.index('def currentSettings', src.index('def apply_app_settings'))]
        self.assertIn('_schedule_npcap_prewarm', apply)


if __name__ == '__main__':
    unittest.main()
