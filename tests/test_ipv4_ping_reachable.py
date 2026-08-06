"""ipv4_ping_reachable must read subprocess stdout, not CompletedProcess repr."""
from __future__ import annotations

import os
import sys
import time
import unittest
from types import SimpleNamespace

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def _load_ipv4_ping_reachable(*, run_command, platform: str = 'win32'):
    """Extract helper without importing tools.utils (utils→scapy can hang)."""
    path = os.path.join(_SRC, 'tools', 'utils.py')
    with open(path, encoding='utf-8') as f:
        src = f.read()
    start = src.index('def ipv4_ping_reachable')
    end = src.index('\ndef victim_endpoint_live_for_mitm')
    ns: dict = {
        'sys': SimpleNamespace(platform=platform),
        'time': time,
        'run_command': run_command,
        '_ipv4_valid': lambda ip: True,
    }
    exec(src[start:end], ns)  # noqa: S102
    return ns['ipv4_ping_reachable']


class TestIpv4PingReachable(unittest.TestCase):
    def test_windows_reads_stdout_ttl(self) -> None:
        proc = SimpleNamespace(
            returncode=0,
            stdout='Reply from 192.168.1.10: bytes=32 time=1ms TTL=64\r\n',
            stderr='',
        )
        fn = _load_ipv4_ping_reachable(run_command=lambda *a, **k: proc)
        self.assertTrue(fn('192.168.1.10', timeout_ms=200))

    def test_windows_false_on_timeout(self) -> None:
        proc = SimpleNamespace(
            returncode=1,
            stdout='Request timed out.\r\n',
            stderr='',
        )
        fn = _load_ipv4_ping_reachable(run_command=lambda *a, **k: proc)
        self.assertFalse(fn('192.168.1.10', timeout_ms=200))


if __name__ == '__main__':
    unittest.main()
