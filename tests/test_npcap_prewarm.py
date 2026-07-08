"""Npcap L2 socket prewarm and multi-token bind."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestNpcapPrewarm(unittest.TestCase):
    @staticmethod
    def _killer_py() -> str:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

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
        clicked = src[src.index('def deviceClicked'): src.index('def _updateLagSwitchButtonState')]
        self.assertIn("_schedule_npcap_prewarm('select')", clicked)

    def test_settings_apply_prewarms_npcap(self) -> None:
        path = os.path.join(_SRC, 'gui', 'settings.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        apply = src[src.index('def apply_app_settings'): src.index('def currentSettings', src.index('def apply_app_settings'))]
        self.assertIn('_schedule_npcap_prewarm', apply)


if __name__ == '__main__':
    unittest.main()
