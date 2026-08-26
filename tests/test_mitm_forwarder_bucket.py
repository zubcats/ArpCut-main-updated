"""Unit tests for MITM forwarder token-bucket helpers."""

from __future__ import annotations

import os
import sys
import time
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from networking.forwarder import MitmForwarder, _mac_key  # noqa: E402


class TestMitmForwarderBucket(unittest.TestCase):
    def test_token_bucket_unlimited(self) -> None:
        fw = MitmForwarder(debug=False)
        fw.max_kbps_from_victim = 0.0
        now = time.monotonic()
        self.assertTrue(fw._token_bucket_allow('out', 1500, now))
        self.assertTrue(fw._token_bucket_allow('out', 1500, now + 0.01))

    def test_token_bucket_caps_burst(self) -> None:
        fw = MitmForwarder(debug=False)
        fw.max_kbps_from_victim = 1000.0  # 125000 bytes/s
        t0 = time.monotonic()
        self.assertTrue(fw._token_bucket_allow('out', 10000, t0))
        # Immediate second huge packet should be denied (no time to refill)
        self.assertFalse(fw._token_bucket_allow('out', 100000, t0 + 0.0001))

    def test_token_bucket_refills(self) -> None:
        fw = MitmForwarder(debug=False)
        fw.max_kbps_to_victim = 8000.0  # 1_000_000 bytes/s
        t0 = time.monotonic()
        self.assertTrue(fw._token_bucket_allow('in', 500000, t0))
        self.assertFalse(fw._token_bucket_allow('in', 500000, t0 + 0.0001))
        # After ~1s should allow another ~1e6 bytes
        self.assertTrue(fw._token_bucket_allow('in', 900000, t0 + 1.1))


class TestMitmForwarderNativeSkip(unittest.TestCase):
    def _fw(self):
        fw = MitmForwarder(debug=False)
        fw.running = True
        fw.my_mac = 'aa:aa:aa:aa:aa:aa'
        fw.victim = {'ip': '192.168.1.248', 'mac': '00:e4:21:44:ed:0c'}
        fw.router = {'ip': '192.168.1.1', 'mac': '74:24:9f:3a:a3:75'}
        fw._sent = []
        fw._send = lambda pkt: fw._sent.append(pkt)
        fw._fix_checksums = lambda pkt: None
        return fw

    def test_mac_key_normalizes_dashes(self) -> None:
        self.assertEqual(_mac_key('AA-AA-AA-AA-AA-AA'), 'aa:aa:aa:aa:aa:aa')

    def test_skips_native_victim_to_router_copies(self) -> None:
        from scapy.all import Ether, IP

        fw = self._fw()
        pkt = Ether(src=fw.victim['mac'], dst=fw.router['mac']) / IP(
            src=fw.victim['ip'], dst='8.8.8.8'
        )
        fw._process_packet(pkt)
        self.assertEqual(fw._pkt_count, 0)
        self.assertEqual(fw._fwd_count, 0)
        self.assertEqual(fw._sent, [])

    def test_skips_our_own_reinject_echo(self) -> None:
        from scapy.all import Ether, IP

        fw = self._fw()
        pkt = Ether(src=fw.my_mac, dst=fw.router['mac']) / IP(
            src=fw.victim['ip'], dst='8.8.8.8'
        )
        fw._process_packet(pkt)
        self.assertEqual(fw._pkt_count, 0)
        self.assertEqual(fw._fwd_count, 0)
        self.assertEqual(fw._sent, [])

    def test_forwards_leftover_mitm_addressed_to_us(self) -> None:
        from scapy.all import Ether, IP

        fw = self._fw()
        pkt = Ether(src=fw.victim['mac'], dst=fw.my_mac) / IP(
            src=fw.victim['ip'], dst='8.8.8.8'
        )
        fw._process_packet(pkt)
        self.assertEqual(fw._pkt_count, 1)
        self.assertEqual(fw._fwd_count, 1)
        self.assertEqual(len(fw._sent), 1)


if __name__ == '__main__':
    unittest.main()
