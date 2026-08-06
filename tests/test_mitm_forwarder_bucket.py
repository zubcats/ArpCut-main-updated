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

from networking.forwarder import MitmForwarder  # noqa: E402


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


if __name__ == '__main__':
    unittest.main()
