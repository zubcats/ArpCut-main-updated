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

    def test_advanced_lag_dialog_constructed_like_main_window(self) -> None:
        tree = ast.parse(_read('src/gui/clumzy_mode_window.py'))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'AdvancedLagSettingsDialog'
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0].args), 1)
        self.assertFalse(calls[0].keywords)

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
        self.assertNotIn('btnAdvancedLag', src)
        self.assertIn('Advanced Lag Settings', src)
        self.assertIn('normalSpinMain', src)
        self.assertIn('btnPercentCut', src)
        self.assertIn('_dim_unavailable_control', src)
        self.assertIn('_lag_allow_ms', src)
        self.assertIn('CYCLE_SETTLE_S', src)
        self.assertIn("QLabel('Normal'", src)
        self.assertIn('spinLagAllowLocked', src)

    def test_settings_greys_unused_clumzy_controls(self) -> None:
        settings = _read('src/gui/settings.py')
        self.assertIn('_apply_clumzy_unavailable_controls', settings)
        self.assertIn('groupBox_4', settings)
        self.assertIn('groupBox_2', settings)

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
        from tools.clumzy_mode_profile import (
            CYCLE_SETTLE_S,
            DROP_CHANCE_PCT,
            FILTER,
            LAG_MS,
            NETWORK_REMOTE,
        )

        self.assertEqual(FILTER, 'true')
        self.assertEqual(NETWORK_REMOTE, 2)
        self.assertEqual(LAG_MS, 100)
        self.assertEqual(DROP_CHANCE_PCT, 100.0)
        self.assertEqual(CYCLE_SETTLE_S, 0.08)

    def test_taskbar_uses_clumzy_white_icon_not_shell(self) -> None:
        branding = _read('src/tools/branding.py')
        self.assertIn("_TASKBAR_ICO_FILE = 'clumzy-icon.ico'", branding)
        self.assertIn("_SHELL_ICO_FILE = 'zubcut_shell.ico'", branding)
        install = branding[branding.index('def install_windows_native_window_icons') :]
        self.assertIn('resolve_zubcut_taskbar_ico_path', install)
        shell_loader = branding[
            branding.index('def load_shell_window_icon') : branding.index(
                'def load_tray_window_icon'
            )
        ]
        self.assertIn('resolve_zubcut_shell_ico_path', shell_loader)
        self.assertNotIn('resolve_zubcut_taskbar_ico_path', shell_loader)
        self.assertTrue(os.path.isfile(os.path.join(_ROOT, 'exe', 'clumzy-icon.ico')))
        build = _read('build.py')
        self.assertIn('exe/clumzy-icon.ico;.', build)
        self.assertIn('exe/zubcut_shell.ico;.', build)
        window = _read('src/gui/clumzy_mode_window.py')
        self.assertIn('install_windows_native_window_icons', window)
        self.assertIn('self.setWindowIcon(self.shell_icon)', window)
        self.assertIn('load_tray_window_icon', window)

    def test_clumzy_mode_creates_system_tray(self) -> None:
        src = _read('src/gui/clumzy_mode_window.py')
        self.assertIn('QSystemTrayIcon', src)
        self.assertIn('self.tray_icon.show()', src)
        self.assertIn('load_tray_window_icon', src)
        self.assertNotIn('self.tray_icon.setIcon(self.shell_icon)', src)
        self.assertNotIn('openKillFlows', src)
        branding = _read('src/tools/branding.py')
        tray_loader = branding[
            branding.index('def load_tray_window_icon') : branding.index('def qicon_is_empty')
        ]
        self.assertIn('resolve_zubcut_taskbar_ico_path', tray_loader)
        main = _read('src/gui/main.py')
        self.assertIn('load_tray_window_icon', main)

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
