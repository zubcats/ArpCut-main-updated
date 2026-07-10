"""Percent Cut must not arm Kill's 0% traffic-cut forwarder before partial pass ratio."""
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


class TestPercentCutKill(unittest.TestCase):
    @staticmethod
    def _killer_py() -> str:
        path = os.path.join(_SRC, 'networking', 'killer.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def _main_py(self) -> str:
        return load_main_window_source()

    def test_kill_supports_traffic_cut_flag(self) -> None:
        src = self._killer_py()
        self.assertIn('traffic_cut=True', src)
        self.assertIn('if not ics_mode and traffic_cut:', src)

    def test_apply_percent_cut_uses_mitm_only_kill(self) -> None:
        src = self._killer_py()
        block = src[src.index('def apply_percent_cut'): src.index('def disable_percent_cut', src.index('def apply_percent_cut'))]
        self.assertIn('traffic_cut=False', block)
        self.assertIn('return False', block)
        self.assertIn('return bool(fw', block)

    def test_toggle_percent_cut_stops_when_ui_shows_on(self) -> None:
        src = self._main_py()
        toggle = methods_through('togglePercentCut', 'stopPercentCut')
        self.assertIn('_percent_cut_ui_shows_on', toggle)
        self.assertIn('stopPercentCut(log=True)', toggle)
        self.assertNotIn('_percent_cut_backend_active', toggle)

    def test_stop_percent_cut_uses_fast_unkill(self) -> None:
        src = self._main_py()
        stop = methods_through('stopPercentCut', '_refresh_advanced_lag_mitm_if_visible')
        self.assertIn('_release_pctcut_victim_immediate', stop)
        self.assertIn('_percent_cut_forwarder_live', stop)
        self.assertIn('_percent_cut_ui_shows_on', methods_through('_updatePercentCutButtonState', '_refresh_flow_toggle_ui'))

    def test_forwarder_percent_pass_is_stochastic(self) -> None:
        from networking.forwarder import MitmForwarder

        fw = MitmForwarder(debug=False)
        passes = sum(1 for _ in range(500) if fw._passes_ratio(50, 'out', 1400))
        self.assertGreater(passes, 150)
        self.assertLess(passes, 350)

    def test_kill_falls_back_to_arp_firewall_when_forwarder_missing(self) -> None:
        src = self._main_py()
        block = src[src.index('Npcap capture failed but ARP poison is live'): src.index(
            "self._schedule_mitm_traffic_probe(device, flow='Kill')",
            src.index('Npcap capture failed but ARP poison is live'),
        )]
        self.assertIn('ARP+firewall', block)
        self.assertIn('_bg_block_ip', block)
        self.assertNotIn('self.killer.unkill(device)', block)

    def test_forwarder_accepts_iface_alts(self) -> None:
        from networking.forwarder import MitmForwarder
        import inspect

        sig = inspect.signature(MitmForwarder.start)
        self.assertIn('iface_alts', sig.parameters)

    def test_killer_uses_npcap_iface_tokens(self) -> None:
        src = self._killer_py()
        block = src[src.index('def apply_percent_cut'): src.index('def disable_percent_cut', src.index('def apply_percent_cut'))]
        self.assertIn('npcap_iface_tokens', block)
        self.assertIn('iface_alts=tokens[1:]', block)


if __name__ == '__main__':
    unittest.main()
