"""Read-only hotspot client list for Clumzy Mode (display only, never a Kill target)."""
from __future__ import annotations

import re
import subprocess
from typing import List

_HOTSPOT_PREFIXES = ('192.168.137.', '192.168.173.')
_ARP_LINE = re.compile(
    r'^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}'
    r'[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2})'
)


def _is_hotspot_client_ip(ip: str) -> bool:
    ip = (ip or '').strip()
    if not any(ip.startswith(p) for p in _HOTSPOT_PREFIXES):
        return False
    if ip.endswith('.255') or ip.endswith('.0'):
        return False
    parts = ip.split('.')
    if len(parts) == 4 and parts[-1] == '1':
        return False
    return True


def parse_hotspot_arp_text(text: str) -> List[dict]:
    rows: List[dict] = []
    seen: set[str] = set()
    for raw in str(text or '').splitlines():
        m = _ARP_LINE.match(raw)
        if not m:
            continue
        ip, mac = m.group(1), m.group(2).replace('-', ':').lower()
        if not _is_hotspot_client_ip(ip):
            continue
        if mac in seen:
            continue
        seen.add(mac)
        rows.append({'ip': ip, 'mac': mac, 'vendor': '', 'type': 'Hotspot', 'name': ''})
    return rows


def list_hotspot_clients() -> List[dict]:
    try:
        completed = subprocess.run(
            ['arp', '-a'],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        blob = (completed.stdout or '') + '\n' + (completed.stderr or '')
    except Exception:
        blob = ''
    return parse_hotspot_arp_text(blob)
