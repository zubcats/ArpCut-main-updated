"""Clumzy Mode isolation and profile tests — no ARP killer imports."""
from __future__ import annotations

import ast
import os
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


class ClumzyModeIsolationTests(unittest.TestCase):
    def test_window_does_not_import_killer_or_scanner(self) -> None:
        tree = ast.parse(_read('src/gui/clumzy_mode_window.py'))
        mods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.append(node.module)
            elif isinstance(node, ast.Import):
                mods.extend(a.name for a in node.names)
        joined = ' '.join(mods)
        self.assertNotIn('networking.killer', joined)
        self.assertNotIn('networking.scanner', joined)
        self.assertNotIn('gui.impairment', joined)
        self.assertNotIn('ics_windivert_shaper', joined)

    def test_startup_fork_exists_before_main_window(self) -> None:
        src = _read('src/zubcut.py')
        fork = src.index('run_clumzy_mode')
        main = src.index('ZubCutApp(window_icon=icon)')
        self.assertLess(fork, main)
        self.assertIn("run_clumzy_mode", src)
        self.assertIn("'clumsy_mode'", src)

    def test_ui_says_clumzy_mode(self) -> None:
        settings = _read('src/gui/settings.py')
        self.assertIn("QCheckBox('Clumzy Mode'", settings)
        self.assertNotIn("QCheckBox('Clumsy Mode'", settings)
        self.assertNotIn("'Install Clumsy mode'", settings)
        self.assertIn("'Install Clumzy Mode'", settings)
        iss = _read('installer/ZubCut.iss')
        self.assertIn('Clumzy Mode', iss)
        self.assertNotIn('Description: "Clumsy mode', iss)

    def test_startup_fork_keeps_license_check(self) -> None:
        src = _read('src/zubcut.py')
        fork = src.index('run_clumzy_mode')
        license_call = src.index('_start_license_runtime_validation(GUI, icon)')
        main = src.index('ZubCutApp(window_icon=icon)')
        self.assertLess(fork, license_call)
        self.assertLess(license_call, main)

    def test_advanced_lag_uses_gated_scheduler(self) -> None:
        src = _read('src/gui/clumzy_mode_window.py')
        self.assertIn('gated_mitm_params', src)
        self.assertIn('all_enabled_timers_finished', src)
        self.assertNotIn('ics_windivert_shaper', src)

    def test_engine_network_type_is_extern(self) -> None:
        hdr = _read('native/clumzy_engine/src/common.h')
        self.assertIn('extern int NetworkType;', hdr)
        api = _read('native/clumzy_engine/src/clumzy_api.c')
        self.assertIn('int NetworkType', api)

    def test_iup_stub_defines_default(self) -> None:
        stub = _read('native/clumzy_engine/include/iup.h')
        self.assertIn('#define IUP_DEFAULT 0', stub)

    def test_freeze_profile(self) -> None:
        import sys

        sys.path.insert(0, _SRC)
        from tools.clumzy_mode_profile import DROP_CHANCE_PCT, FILTER, LAG_MS, NETWORK_REMOTE

        self.assertEqual(FILTER, 'true')
        self.assertEqual(NETWORK_REMOTE, 2)
        self.assertEqual(LAG_MS, 100)
        self.assertEqual(DROP_CHANCE_PCT, 100.0)

    def test_hotspot_arp_parse_skips_gateway(self) -> None:
        import sys

        sys.path.insert(0, _SRC)
        from tools.clumzy_hotspot_view import parse_hotspot_arp_text

        text = (
            'Interface: 192.168.137.1 --- 0x12\n'
            '  192.168.137.1         aa-aa-aa-aa-aa-01     dynamic\n'
            '  192.168.137.42        bb-bb-bb-bb-bb-bb     dynamic\n'
            '  192.168.1.50          cc-cc-cc-cc-cc-cc     dynamic\n'
        )
        rows = parse_hotspot_arp_text(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ip'], '192.168.137.42')


if __name__ == '__main__':
    unittest.main()
