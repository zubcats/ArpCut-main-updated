"""Hardening guards: netsh validation, remember-kill filter, ICS ghost sync, packaging."""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _gui_source import load_main_window_source, methods_through, method_src


class TestPfctlValidation(unittest.TestCase):
    def test_safe_rule_name_rejects_metacharacters(self) -> None:
        from tools.pfctl import _safe_zubcut_rule_name

        self.assertEqual(_safe_zubcut_rule_name('zubcut_1_2_3_to_4_5_6'), 'zubcut_1_2_3_to_4_5_6')
        self.assertIsNone(_safe_zubcut_rule_name('evil'))
        self.assertIsNone(_safe_zubcut_rule_name('zubcut_"&calc'))
        self.assertIsNone(_safe_zubcut_rule_name('zubcut_x|y'))

    def test_block_dst_rejects_bad_ip(self) -> None:
        from tools import pfctl

        self.assertFalse(pfctl.block_dst('eth0', 'not-an-ip', '1.2.3.4'))
        self.assertFalse(pfctl.block_dst('eth0', '1.2.3.4', '999.1.1.1'))
        self.assertFalse(pfctl.block_dst('eth0', '1.2.3.4', '8.8.8.8', port=99999))


class TestRememberKillFilter(unittest.TestCase):
    def test_write_remembered_uses_should_restore(self) -> None:
        src = load_main_window_source()
        block = methods_through('_write_remembered_killed_macs', '_device_with_plan_ip')
        self.assertIn('should_restore_remembered_kill', block)
        self.assertNotIn("list(self.killer.killed.keys())", block)

    def test_process_devices_remembered_restore_uses_full_arm(self) -> None:
        """Cold post-scan restore must not use fast_arm (silent re-arm failures)."""
        block = method_src('processDevices')
        self.assertIn('should_restore_remembered_kill', block)
        self.assertIn("fast_arm=False", block)
        # LAN remember path must not force instant arm.
        remember_chunk = block.split('should_restore_remembered_kill', 1)[1].split(
            'elif self._is_ics_downstream', 1
        )[0]
        self.assertIn('fast_arm=False', remember_chunk)
        self.assertNotIn('fast_arm=True', remember_chunk)
        self.assertIn('Remembered kill restore failed', remember_chunk)


class TestIcsKillGhostSync(unittest.TestCase):
    def test_sync_clears_ics_profiles_without_backend(self) -> None:
        src = load_main_window_source()
        block = methods_through('_sync_killed_devices', '_set_kill_button_idle_look')
        self.assertNotIn(
            "if mac in getattr(self, '_ics_kill_profile_macs', set()):\n                continue",
            block,
        )
        self.assertIn('_ics_kill_profile_macs', block)
        self.assertIn('_explicit_kill_backend_live', block)


class TestDupeReleaseOnGuiThread(unittest.TestCase):
    def test_stop_dupe_releases_sync_on_gui_stack(self) -> None:
        """UI OFF must unkill immediately (Lag parity) — not wait a QTimer tick."""
        src = load_main_window_source()
        block = methods_through('stopDupe', '_updateDupeButtonState')
        self.assertIn('_release_dupe_victim_immediate(release_snap, refresh_context=False)', block)
        self.assertNotIn('QTimer.singleShot(0, _release_on_gui)', block)
        self.assertNotIn('_dupe_net_executor.submit(_release_worker)', block)
        self.assertIn('_dupe_start_gen', block)

    def test_stop_dupe_reconnects_deferred_clear_and_drops_gate(self) -> None:
        """Snap-path OFF must not leave teardown latched ('still restoring')."""
        stop = method_src('stopDupe')
        # Sync release then deferred firewall clear; reconnect before start(0).
        self.assertIn('_release_dupe_victim_immediate(release_snap, refresh_context=False)', stop)
        self.assertIn('_drop_dupe_restoring_banner()', stop)
        snap_arm = stop.split('_release_dupe_victim_immediate(release_snap, refresh_context=False)', 1)[1]
        snap_arm = snap_arm.split('return', 1)[0]
        self.assertIn('_dupe_deferred_clear_timer.timeout.disconnect()', snap_arm)
        self.assertIn('_do_deferred_dupe_clear', snap_arm)
        self.assertIn('UniqueConnection', snap_arm)


class TestPercentCutRowUi(unittest.TestCase):
    def test_percent_cut_ui_false_for_other_row(self) -> None:
        src = load_main_window_source()
        block = methods_through('_percent_cut_ui_shows_on', '_updatePercentCutButtonState')
        self.assertIn('return False', block)
        self.assertNotIn('return bool(stored_mac or stored_ip)', block.split('if stored_ip')[-1])


class TestCustomerBuildExcludesAdmin(unittest.TestCase):
    def test_build_py_excludes_control_panel(self) -> None:
        path = os.path.join(_ROOT, 'build.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'gui.control_panel'", src)
        self.assertIn('--exclude-module', src)
        self.assertNotIn("--collect-submodules', 'gui'", src.replace('"', "'"))
        self.assertNotIn('--collect-submodules", "gui"', src)


class TestCrashWorkerHardening(unittest.TestCase):
    def test_worker_has_rate_limit_and_optional_token(self) -> None:
        path = os.path.join(_ROOT, 'backend', 'cloudflare-license-signin', 'worker.mjs')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('crashIngestAuthorized', src)
        self.assertIn('enforceCrashRateLimit', src)
        self.assertIn('CRASH_INGEST_TOKEN', src)
        self.assertIn('429', src)


class TestSingleInstanceGuard(unittest.TestCase):
    def test_duplicate_zubcut_implemented(self) -> None:
        path = os.path.join(_SRC, 'tools', 'utils_gui.py')
        with open(path, encoding='utf-8') as f:
            src = f.read()
        block = src[src.index('def duplicate_zubcut'): src.index('def check_documents_dir')]
        self.assertIn('CreateMutexW', block)
        self.assertIn('wait_s', block)
        self.assertIn('def release_zubcut_single_instance', src)
        zpath = os.path.join(_SRC, 'zubcut.py')
        with open(zpath, encoding='utf-8') as f:
            zsrc = f.read()
        self.assertIn('clumsy_settings_restart_pending', zsrc)
        self.assertIn('duplicate_zubcut(wait_s=', zsrc)
        self.assertNotIn('not implemented', block.lower())


if __name__ == '__main__':
    unittest.main()
