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
        self.assertIn('wait_after=0.0', block)
        self.assertIn('return False', block)
        self.assertIn('return bool(fw', block)

    def test_pctcut_instant_apply_helper_exists(self) -> None:
        src = self._main_py()
        self.assertIn('def _pctcut_instant_apply', src)
        helper = src[src.index('def _pctcut_instant_apply'): src.index('def _release_dupe_victim_immediate')]
        self.assertIn('gate.apply_percent_cut', helper)
        self.assertIn('apply_percent_cut(dev, pass_percent=allow_pct)', helper)
        self.assertNotIn('traffic_cut=True', helper)

    def test_toggle_percent_cut_stops_when_ui_shows_on(self) -> None:
        src = self._main_py()
        toggle = methods_through('togglePercentCut', 'stopPercentCut')
        self.assertIn('_percent_cut_ui_shows_on', toggle)
        self.assertIn('stopPercentCut(log=True)', toggle)
        self.assertNotIn('_percent_cut_backend_active', toggle)

    def test_stop_percent_cut_uses_fast_unkill(self) -> None:
        src = self._main_py()
        stop = method_src('stopPercentCut')
        self.assertIn('_pctcut_instant_resume', stop)
        self.assertIn('QTimer.singleShot(0, _finish_off)', stop)
        # Paint first; resume/unkill on this stack; delayed reinforce only in _finish_off.
        paint = stop.index("btnPercentCut.setText(f'Percent Cut: {pct}%')")
        resume = stop.index('_pctcut_instant_resume')
        defer = stop.index('QTimer.singleShot(0, _finish_off)')
        self.assertLess(paint, resume)
        self.assertLess(resume, defer)
        self.assertIn('_schedule_pctcut_off_reinforce', stop)
        self.assertIn('_pctcut_off_until', stop)
        self.assertNotIn('_release_pctcut_victim_immediate', stop.split('def _finish_off')[0])
        resume_fn = method_src('_pctcut_instant_resume')
        self.assertIn('killer.unkill', resume_fn)
        self.assertIn('reinforce_restore', resume_fn)
        self.assertIn('_ensure_network_context_for_victim', resume_fn)
        self.assertIn('_release_victim_arp_mitm_stack', resume_fn)
        self.assertIn('resume_percent_cut_live', resume_fn)
        self.assertIn('pass_all_live', self._forwarder_py())
        # Second OFF click must clear residue instead of re-arming ON.
        toggle = methods_through('togglePercentCut', 'stopPercentCut')
        self.assertIn('_percent_cut_forwarder_live', toggle)
        self.assertIn('_killed_profile_on', toggle)
        self.assertIn("_ignore_duplicate_toggle_edge('pctcut'", toggle)
        self.assertIn('_pctcut_undo_cancelled_arm', toggle)
        self.assertIn('_pctcut_start_cancelled', toggle)

    @staticmethod
    def _forwarder_py() -> str:
        path = os.path.join(_SRC, 'networking', 'forwarder.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

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
