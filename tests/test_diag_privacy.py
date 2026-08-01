"""Screenshot-safe IP redaction for diagnostic reports."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tools.diag_privacy import redact_ipv4, redact_ipv4s_in_text, same_ipv4_subnet  # noqa: E402


class TestDiagPrivacy(unittest.TestCase):
    def test_redact_private_keeps_subnet_and_host(self) -> None:
        self.assertEqual(redact_ipv4('192.168.1.56'), '192.168.1.0/24 host .56')
        self.assertEqual(redact_ipv4('10.0.0.2'), '10.0.0.0/24 host .2')

    def test_redact_hotspot_and_apipa(self) -> None:
        self.assertEqual(redact_ipv4('192.168.137.22'), 'hotspot 137 / .22')
        self.assertEqual(redact_ipv4('169.254.10.20'), 'apipa / .10.20')

    def test_redact_public(self) -> None:
        self.assertEqual(redact_ipv4('8.8.8.8'), 'public / .8')

    def test_same_subnet(self) -> None:
        self.assertTrue(same_ipv4_subnet('192.168.1.56', '192.168.1.1'))
        self.assertFalse(same_ipv4_subnet('192.168.1.56', '192.168.0.1'))

    def test_redact_in_text(self) -> None:
        text = 'PC 192.168.1.56 GW 192.168.1.1 hotspot 192.168.137.2'
        out = redact_ipv4s_in_text(text)
        self.assertNotIn('192.168.1.56', out)
        self.assertIn('192.168.1.0/24 host .56', out)
        self.assertIn('hotspot 137 / .2', out)


class TestQuickDiagPrivacySource(unittest.TestCase):
    def test_ps1_has_redaction_and_new_checks(self) -> None:
        path = _ROOT / 'tools' / 'ZubCut-Quick-Network-Diag.ps1'
        src = path.read_text(encoding='utf-8')
        self.assertIn('Format-SafeIPv4', src)
        self.assertIn('IP forwarding off', src)
        self.assertIn('Gateway MAC known', src)
        self.assertIn('Npcap/NPF service running', src)
        self.assertIn('Settings adapter live', src)
        self.assertIn('redacted', src.lower())
        # Full IPs should not appear as bare summary examples with common LAN forms
        # in the template — dynamic only via Format-SafeIPv4.
        self.assertIn('subnet + host', src)


if __name__ == '__main__':
    unittest.main()
