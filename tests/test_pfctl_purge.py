"""Tests for Windows firewall purge helpers."""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools import pfctl


class PfctlPurgeTests(unittest.TestCase):
    def test_purge_function_exists(self) -> None:
        self.assertTrue(callable(pfctl.windows_purge_all_zubcut_ip_block_rules))
        self.assertTrue(callable(pfctl.teardown_all_zubcut_network_attacks))

    def test_purge_non_windows_returns_zero(self) -> None:
        if sys.platform.startswith('win'):
            return
        self.assertEqual(pfctl.windows_purge_all_zubcut_ip_block_rules(), 0)

    def test_stdout_lines_handles_none_stdout(self) -> None:
        from types import SimpleNamespace

        self.assertEqual(pfctl._stdout_lines(SimpleNamespace(stdout=None)), [])

    def test_list_blocked_ips_survives_none_stdout(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        fake = SimpleNamespace(returncode=0, stdout=None, stderr='')
        with patch.object(pfctl, '_exec', return_value=fake):
            self.assertEqual(pfctl.list_blocked_ips(), [])

    def test_attack_rule_detection(self) -> None:
        self.assertTrue(pfctl._zubcut_rule_is_attack('zubcut_ip_192_168_1_1_in'))
        self.assertTrue(pfctl._zubcut_rule_is_attack('zubcut_port_443_tcp_in'))
        self.assertTrue(pfctl._zubcut_rule_is_attack('zubcut_10_0_0_1_to_8_8_8_8'))
        self.assertFalse(pfctl._zubcut_rule_is_attack('ZubCut-DHCP-In'))
        self.assertFalse(pfctl._zubcut_rule_is_attack('ZubCut-ICS-DHCP-Subnet-In'))
        self.assertFalse(pfctl._zubcut_rule_is_attack('ZubCut-Hotspot-Subnet-In'))
