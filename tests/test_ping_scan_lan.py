"""Ping Scan on the LAN path must sweep DHCP IPs, not only .1–.24."""
from __future__ import annotations

import os
import sys
import types
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SRC = os.path.join(_ROOT, 'src')


def _scanner_src() -> str:
    path = os.path.join(_SRC, 'networking', 'scanner.py')
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _load_ping_helpers():
    """Exec Ping Scan helpers without importing scapy/scanner."""
    src = _scanner_src()
    start = src.index('    def generate_ips(self, *, thorough: bool = False):')
    end = src.index('    def init(self):')
    body = src[start:end]
    dedented = '\n'.join(
        line[4:] if line.startswith('    ') else line for line in body.splitlines()
    )
    ns: dict = {
        'sys': types.SimpleNamespace(platform='win32'),
        '_is_softap_ipv4': lambda ip: str(ip or '').startswith(
            ('192.168.137.', '192.168.173.')
        ),
        '_softap_bind_allowed': lambda: False,
        'iface_ipv4_prefix_len': lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('no scapy')
        ),
    }
    exec(dedented, ns)  # noqa: S102

    class _S:
        generate_ips = ns['generate_ips']
        _lan_ping_prefix = ns['_lan_ping_prefix']
        _ping_last_octet_range = ns['_ping_last_octet_range']
        _ping_source_ok = ns['_ping_source_ok']
        _icmp_ping_argv = ns['_icmp_ping_argv']

    return _S


class TestPingScanLan(unittest.TestCase):
    def test_default_count_misses_consoles_thorough_does_not(self) -> None:
        S = _load_ping_helpers()
        s = S()
        s.device_count = 25
        s.perfix = '192.168.1'
        s.my_ip = '192.168.1.56'
        s.router_ip = '192.168.1.1'
        s.iface = None
        s.generate_ips()
        self.assertNotIn('192.168.1.165', s.ips)
        self.assertNotIn('192.168.1.248', s.ips)
        s.generate_ips(thorough=True)
        self.assertIn('192.168.1.1', s.ips)
        self.assertIn('192.168.1.165', s.ips)
        self.assertIn('192.168.1.248', s.ips)
        self.assertNotIn('192.168.1.56', s.ips)
        self.assertNotIn('192.168.1.255', s.ips)
        self.assertEqual(len(s.ips), 253)

    def test_softap_leftover_prefix_uses_home_gateway(self) -> None:
        S = _load_ping_helpers()
        s = S()
        s.device_count = 25
        s.perfix = '192.168.137'
        s.my_ip = '192.168.137.1'
        s.router_ip = '192.168.1.1'
        s.iface = None
        s.generate_ips(thorough=True)
        self.assertIn('192.168.1.165', s.ips)
        self.assertTrue(all(ip.startswith('192.168.1.') for ip in s.ips))

    def test_icmp_binds_lan_source_and_times_out(self) -> None:
        S = _load_ping_helpers()
        s = S()
        s.my_ip = '192.168.1.56'
        argv = s._icmp_ping_argv('192.168.1.165')
        self.assertEqual(argv[:4], ['ping', '-n', '1', '-w'])
        self.assertIn('-S', argv)
        self.assertEqual(argv[argv.index('-S') + 1], '192.168.1.56')
        self.assertEqual(argv[-1], '192.168.1.165')

    def test_ping_scan_runs_inline_full_prefix(self) -> None:
        src = _scanner_src()
        self.assertIn('generate_ips(thorough=True)', src)
        self.assertIn("argv = ['ping', '-n', '1', '-w', '400']", src)
        ping_scan = src[src.index('    def ping_scan(self):') : src.index('    def ping_thread_pool(self):')]
        self.assertNotIn('while True', ping_scan)
        pool = src[src.index('    def ping_thread_pool(self):') : src.index('    def ping(self, ip):')]
        self.assertNotIn('@threaded', pool)

    def test_progress_bar_matches_slash24_sweep(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('scan_max = 254 if scan_type else self.scanner.device_count', src)


if __name__ == '__main__':
    unittest.main()
