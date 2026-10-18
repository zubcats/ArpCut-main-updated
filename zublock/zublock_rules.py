"""ZubLock drop rules. Standalone — not part of ZubCut."""
from __future__ import annotations

import ipaddress
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RANGES_PATH = ROOT / 'lock_ranges.txt'


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
