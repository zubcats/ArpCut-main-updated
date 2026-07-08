"""PS5 Wi‑Fi ↔ wired handoff must not leave stale MITM on sibling MACs/IPs."""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestWifiWiredHandoff(unittest.TestCase):
    @staticmethod
    def _main_py() -> str:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_flow_start_resolves_live_lan_victim(self) -> None:
        src = self._main_py()
        fn = src[src.index('def _resolve_flow_start_device'): src.index('def _console_historical_ips')]
        self.assertIn('resolve_live_lan_victim', fn)
        self.assertIn('_purge_stale_console_mitm', fn)

    def test_teardown_includes_nickname_historical_ips(self) -> None:
        src = self._main_py()
        fn = src[src.index('def _victim_teardown_ips'): src.index('def _release_victim_arp_mitm_stack')]
        self.assertIn('_console_historical_ips', fn)

    def test_ensure_network_context_purges_sibling_mitm(self) -> None:
        src = self._main_py()
        fn = src[src.index('def _ensure_network_context_for_victim'): src.index('def _resolve_flow_start_device')]
        self.assertIn('_purge_stale_console_mitm', fn)

    def test_purge_uses_allowed_macs(self) -> None:
        src = self._main_py()
        fn = src[src.index('def _purge_stale_console_mitm'): src.index('def _clear_stale_ics_mitm')]
        self.assertIn("_resolve_allowed_macs", fn)
        self.assertIn("getattr(self.killer, 'killed'", fn)


if __name__ == '__main__':
    unittest.main()
