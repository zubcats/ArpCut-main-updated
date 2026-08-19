"""Scapy must not bind the dummy NULL iface (startup crash ZC-236TTZ)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from constants import DUMMY_IFACE
from networking.ifaces import NetFace
from tools.utils import bind_scapy_conf_iface, scapy_iface_token_ok


class TestBindScapyConfIface(unittest.TestCase):
    def test_null_and_empty_tokens_are_rejected(self) -> None:
        self.assertFalse(scapy_iface_token_ok('NULL'))
        self.assertFalse(scapy_iface_token_ok('null'))
        self.assertFalse(scapy_iface_token_ok(''))
        self.assertFalse(scapy_iface_token_ok(None))
        self.assertTrue(scapy_iface_token_ok(r'\\Device\\NPF_{GUID}'))

    def test_bind_skips_null_without_touching_conf(self) -> None:
        with patch('tools.utils.conf') as conf:
            self.assertFalse(bind_scapy_conf_iface('NULL'))
            self.assertFalse(bind_scapy_conf_iface(''))
            self.assertEqual(conf.mock_calls, [])

    def test_bind_swallows_scapy_valueerror(self) -> None:
        class _Conf:
            def __setattr__(self, name, val):
                if name == 'iface':
                    raise ValueError("Interface '%s' not found !" % val)
                super().__setattr__(name, val)

        with patch('tools.utils.conf', _Conf()):
            self.assertFalse(bind_scapy_conf_iface(r'\\Device\\NPF_{MISSING}'))

    def test_killer_init_survives_dummy_null_iface(self) -> None:
        dummy = NetFace(DUMMY_IFACE)
        with patch('networking.killer.get_default_iface', return_value=dummy):
            with patch('networking.killer.conf') as conf:
                type(conf).iface = property(
                    lambda _self: None,
                    lambda _self, val: (_ for _ in ()).throw(
                        ValueError("Interface '%s' not found !" % val)
                    ),
                )
                from networking.killer import Killer

                killer = Killer()
        self.assertEqual(killer.iface.name, 'NULL')
