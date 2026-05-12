"""Unit tests for MITM forwarder token-bucket helpers."""

import time

from networking.forwarder import MitmForwarder


def test_token_bucket_unlimited():
    fw = MitmForwarder(debug=False)
    fw.max_kbps_from_victim = 0.0
    now = time.monotonic()
    assert fw._token_bucket_allow('out', 1500, now) is True
    assert fw._token_bucket_allow('out', 1500, now + 0.01) is True


def test_token_bucket_caps_burst():
    fw = MitmForwarder(debug=False)
    fw.max_kbps_from_victim = 1000.0  # 125000 bytes/s
    t0 = time.monotonic()
    assert fw._token_bucket_allow('out', 10000, t0) is True
    # Immediate second huge packet should be denied (no time to refill)
    assert fw._token_bucket_allow('out', 100000, t0 + 0.0001) is False


def test_token_bucket_refills():
    fw = MitmForwarder(debug=False)
    fw.max_kbps_to_victim = 8000.0  # 1_000_000 bytes/s
    t0 = time.monotonic()
    assert fw._token_bucket_allow('in', 500000, t0) is True
    assert fw._token_bucket_allow('in', 500000, t0 + 0.0001) is False
    # After ~1s should allow another ~1e6 bytes
    assert fw._token_bucket_allow('in', 900000, t0 + 1.1) is True
