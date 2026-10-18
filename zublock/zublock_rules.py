"""ZubLock drop rules. Standalone — not part of ZubCut."""
from __future__ import annotations

import bisect
import ipaddress
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RANGES_PATH = ROOT / 'lock_ranges.txt'
AWS_PATH = ROOT / 'aws_ipv4.txt'
_FALLBACK_AWS = (
    '44.234.0.0/16',
    '35.164.0.0/15',
    '35.155.0.0/16',
    '100.20.0.0/14',
)
_AWS_STARTS: tuple[int, ...] = ()
_AWS_ENDS: tuple[int, ...] = ()


def parse_drop_keys(text: str) -> set[tuple[str, str, int]]:
    """Parse lines like ``TCP/1.2.3.4:443`` or ``TCP/44.234.0.0/16:443``."""
    out: set[tuple[str, str, int]] = set()
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.upper() == 'WAN':
            out.add(('WAN', '', 0))
            continue
        if line.upper() == 'AWS':
            out.add(('AWS', '', 443))
            continue
        if line.upper() == 'NEWSYN':
            out.add(('NEWSYN', '', 0))
            continue
        try:
            proto, rest = line.split('/', 1)
            host, port_s = rest.rsplit(':', 1)
            proto = proto.strip().upper()
            if proto not in ('TCP', 'UDP', 'IP', 'WAN', 'NEWSYN'):
                continue
            port = int(port_s) if port_s not in ('*', '') else 0
            if not (0 <= port <= 65535):
                continue
            out.add((proto, host.strip(), port))
        except Exception:
            continue
    return out


def load_ranges(path: Path | None = None) -> set[tuple[str, str, int]]:
    target = path or RANGES_PATH
    rules = parse_drop_keys(target.read_text(encoding='utf-8'))
    if not rules:
        raise RuntimeError(f'no lock rules in {target}')
    return rules


def _load_aws_table() -> None:
    global _AWS_STARTS, _AWS_ENDS
    if _AWS_STARTS:
        return
    lines: list[str]
    if AWS_PATH.is_file():
        lines = AWS_PATH.read_text(encoding='utf-8').splitlines()
    else:
        lines = list(_FALLBACK_AWS)
    ranges: list[list[int]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        try:
            net = ipaddress.ip_network(line, strict=False)
        except Exception:
            continue
        if net.version != 4:
            continue
        ranges.append([int(net.network_address), int(net.broadcast_address)])
    ranges.sort()
    merged: list[list[int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    _AWS_STARTS = tuple(row[0] for row in merged)
    _AWS_ENDS = tuple(row[1] for row in merged)


def is_aws_ipv4(ip: str) -> bool:
    """True if IPv4 is in Amazon's published AWS space."""
    if not ip or ':' in ip:
        return False
    _load_aws_table()
    try:
        n = int(ipaddress.IPv4Address(ip))
    except Exception:
        return False
    i = bisect.bisect_right(_AWS_STARTS, n) - 1
    return i >= 0 and n <= _AWS_ENDS[i]


def _host_hit(rule_host: str, ip: str) -> bool:
    if not rule_host or not ip:
        return False
    if '/' in rule_host:
        try:
            return ipaddress.ip_address(ip) in ipaddress.ip_network(rule_host, strict=False)
        except Exception:
            return False
    return ip == rule_host


def should_drop(
    ip_src: str,
    ip_dst: str,
    proto: str,
    sport: int,
    dport: int,
    rules: set[tuple[str, str, int]],
    flags: str = '',
) -> bool:
    fl = (flags or '').upper()
    for p, host, port in rules:
        if p == 'NEWSYN':
            if proto != 'TCP' or 'S' not in fl:
                continue
            if 53 in (sport, dport):
                continue
            try:
                if ipaddress.ip_address(ip_src).is_private and ipaddress.ip_address(ip_dst).is_private:
                    continue
            except Exception:
                continue
            return True
        if p == 'AWS':
            if proto != 'TCP' or 443 not in (sport, dport):
                continue
            return is_aws_ipv4(ip_src) or is_aws_ipv4(ip_dst)
        if p == 'WAN':
            try:
                if ipaddress.ip_address(ip_src).is_private and ipaddress.ip_address(ip_dst).is_private:
                    continue
            except Exception:
                continue
            if proto == 'UDP' and 53 in (sport, dport):
                continue
            return True
        if p == 'IP' and (_host_hit(host, ip_src) or _host_hit(host, ip_dst)):
            return True
        if p != proto:
            continue
        if _host_hit(host, ip_dst) and (port == 0 or dport == port):
            return True
        if _host_hit(host, ip_src) and (port == 0 or sport == port):
            return True
    return False
