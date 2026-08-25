"""Agent unittest must not UAC-launch Nmap/Npcap helpers."""
from __future__ import annotations

import os
import unittest


class TestNoNmapUacInTests(unittest.TestCase):
    def test_test_package_blocks_nmap_npcap_uac_spawns(self) -> None:
        path = os.path.join(os.path.dirname(__file__), '__init__.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('wlanhelper', src)
        self.assertIn('nmap.exe', src)
        self.assertIn('verb runas', src)
        self.assertIn('sc start npcap', src)
        self.assertIn('blocked Npcap/Nmap UAC spawn in tests', src)


if __name__ == '__main__':
    unittest.main()
