"""Behavioral tests for ImpairmentController (toggle gating + teardown gate)."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from gui.impairment_controller import ImpairmentController, ImpairmentTeardownGate


class TestImpairmentController(unittest.TestCase):
    def test_lag_blocks_pctcut(self) -> None:
        st = SimpleNamespace(
            lag_active=True,
            lag_device_mac='aa:bb:cc:dd:ee:ff',
            dupe_active=False,
            dupe_device_mac=None,
            percent_cut_active=False,
            percent_cut_device_mac=None,
            mitm_shaping_active=False,
            mitm_shaping_mac=None,
            killed_devices={},
        )
        logs = []
        ctrl = ImpairmentController(
            state_provider=lambda: st,
            log=lambda msg, kind: logs.append((msg, kind)),
        )
        self.assertEqual(ctrl.active_toggle_kind(), 'lag')
        self.assertTrue(ctrl.toggle_start_blocked('pctcut'))
        self.assertTrue(logs)

    def test_kill_same_victim_allows_dupe(self) -> None:
        st = SimpleNamespace(
            lag_active=False,
            lag_device_mac=None,
            dupe_active=False,
            dupe_device_mac=None,
            percent_cut_active=False,
            percent_cut_device_mac=None,
            mitm_shaping_active=False,
            mitm_shaping_mac=None,
            killed_devices={'aa:bb:cc:dd:ee:ff|192.168.1': True},
        )
        ctrl = ImpairmentController(
            state_provider=lambda: st,
            killed_profile_on=lambda _dev: True,
        )
        self.assertFalse(ctrl.toggle_start_blocked('dupe', {'mac': 'aa:bb:cc:dd:ee:ff'}))

    def test_teardown_gate_blocks_new_start(self) -> None:
        st = SimpleNamespace(
            lag_active=False,
            lag_device_mac=None,
            dupe_active=False,
            dupe_device_mac=None,
            percent_cut_active=False,
            percent_cut_device_mac=None,
            mitm_shaping_active=False,
            mitm_shaping_mac=None,
            killed_devices={},
        )
        gate = ImpairmentTeardownGate()
        self.assertTrue(gate.begin('dupe', 'aa:bb:cc:dd:ee:ff'))
        self.assertFalse(gate.begin('kill', 'aa:bb:cc:dd:ee:ff'))
        ctrl = ImpairmentController(state_provider=lambda: st, teardown_gate=gate)
        self.assertTrue(ctrl.toggle_start_blocked('kill'))
        gate.end('dupe')
        self.assertFalse(ctrl.toggle_start_blocked('kill'))

    def test_edge_debounce(self) -> None:
        st = SimpleNamespace(
            lag_active=False,
            lag_device_mac=None,
            dupe_active=False,
            dupe_device_mac=None,
            percent_cut_active=False,
            percent_cut_device_mac=None,
            mitm_shaping_active=False,
            mitm_shaping_mac=None,
            killed_devices={},
        )
        ctrl = ImpairmentController(state_provider=lambda: st)
        self.assertFalse(ctrl.ignore_duplicate_toggle_edge('kill', 'aa:bb', 'on'))
        self.assertTrue(ctrl.ignore_duplicate_toggle_edge('kill', 'aa:bb', 'on'))
        self.assertFalse(ctrl.ignore_duplicate_toggle_edge('kill', 'aa:bb', 'off'))


class TestUpdaterPublisherPin(unittest.TestCase):
    def test_validate_requires_matching_thumbprint_when_configured(self) -> None:
        import tempfile
        from unittest import mock
        from tools import updater_core as uc

        with tempfile.NamedTemporaryFile(suffix='.exe', delete=False) as fh:
            fh.write(b'MZ' + b'\0' * 2048)
            path = fh.name
        try:
            with mock.patch.object(
                uc,
                '_authenticode_signature_info',
                return_value={'status': 'Valid', 'thumbprint': 'AAAABBBB'},
            ), mock.patch.object(
                uc, '_configured_publisher_thumbprints', return_value=('CCCCDDDD',)
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    uc._validate_installer_exe(path)
                self.assertIn('publisher', str(ctx.exception).lower())
            with mock.patch.object(
                uc,
                '_authenticode_signature_info',
                return_value={'status': 'Valid', 'thumbprint': 'CCCCDDDD'},
            ), mock.patch.object(
                uc, '_configured_publisher_thumbprints', return_value=('CCCCDDDD',)
            ):
                uc._validate_installer_exe(path)
        finally:
            os.unlink(path)

    def test_unsigned_allowed_without_publisher_pin(self) -> None:
        import tempfile
        from unittest import mock
        from tools import updater_core as uc

        with tempfile.NamedTemporaryFile(suffix='.exe', delete=False) as fh:
            fh.write(b'MZ' + b'\0' * 2048)
            path = fh.name
        try:
            with mock.patch.object(
                uc, '_configured_publisher_thumbprints', return_value=()
            ):
                # No pin → signature probe returns {} and validation still passes.
                self.assertEqual(uc._authenticode_signature_info(path), {})
                uc._validate_installer_exe(path)
        finally:
            os.unlink(path)

    def test_authenticode_probe_hidden_when_pin_configured(self) -> None:
        import inspect
        from tools import updater_core as uc

        src = inspect.getsource(uc._authenticode_signature_info)
        self.assertIn('_windows_subprocess_no_window_kwargs', src)
        self.assertIn('WindowStyle', src)
        self.assertIn('Hidden', src)


class TestSecretRewrap(unittest.TestCase):
    def test_rewrap_secret_passthrough_without_dpapi(self) -> None:
        from unittest import mock

        from tools import secret_store as ss

        # Windows CI has real DPAPI; force the non-Windows path so this asserts
        # passthrough rather than encrypting into a dpapi: blob.
        with mock.patch.object(ss, '_dpapi_available', return_value=False):
            out, note = ss.rewrap_secret('plain-secret')
        self.assertEqual(note, '')
        self.assertEqual(out, 'plain-secret')

    def test_rewrap_secret_protects_when_dpapi_mocked(self) -> None:
        from unittest import mock

        from tools import secret_store as ss

        with mock.patch.object(ss, '_dpapi_available', return_value=True), mock.patch.object(
            ss, 'protect_secret', return_value='dpapi:ZmFrZQ=='
        ), mock.patch.object(ss, 'unprotect_secret', side_effect=lambda s: s):
            out, note = ss.rewrap_secret('plain-secret')
        self.assertEqual(note, '')
        self.assertEqual(out, 'dpapi:ZmFrZQ==')


if __name__ == '__main__':
    unittest.main()
