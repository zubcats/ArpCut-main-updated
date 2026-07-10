"""PS5 Wi‑Fi ↔ wired handoff must not leave stale MITM on sibling MACs/IPs."""
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


class TestWifiWiredHandoff(unittest.TestCase):
    def _main_py(self) -> str:
        return load_main_window_source()

    def test_flow_start_resolves_live_lan_victim(self) -> None:
        src = self._main_py()
        fn = methods_through('_resolve_flow_start_device', '_console_historical_ips')
        self.assertIn('resolve_live_lan_victim', fn)
        self.assertNotIn('_purge_stale_console_mitm', fn)

    def test_teardown_includes_nickname_historical_ips(self) -> None:
        src = self._main_py()
        fn = methods_through('_victim_teardown_ips', '_release_victim_arp_mitm_stack')
        self.assertIn('_console_historical_ips', fn)

    def test_release_stack_collects_console_siblings(self) -> None:
        src = self._main_py()
        fn = methods_through('_release_victim_arp_mitm_stack', '_ics_gate_allow_traffic')
        self.assertIn('_console_sibling_victims', fn)

    def test_no_sync_unkill_on_flow_start(self) -> None:
        src = self._main_py()
        self.assertNotIn('def _purge_stale_console_mitm', src)
        ensure = methods_through('_ensure_network_context_for_victim', '_resolve_flow_start_device')
        self.assertNotIn('unkill', ensure)


if __name__ == '__main__':
    unittest.main()
