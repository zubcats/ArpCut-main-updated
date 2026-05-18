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

    def test_purge_non_windows_returns_zero(self) -> None:
        if sys.platform.startswith('win'):
            return
        self.assertEqual(pfctl.windows_purge_all_zubcut_ip_block_rules(), 0)
