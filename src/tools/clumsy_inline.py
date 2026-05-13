"""
Clumsy mode (Windows): ICS / inline-console helpers — no synthetic table row.

When clumsy mode is enabled and the WinDivert bundle is ready, sync_clumsy_row()
strips legacy synthetic rows and deduplicates multiple scan entries that share the
ICS client IPv4 (keeps the first non-admin row).
"""
from __future__ import annotations

import os
import re
import sys
import time
from typing import TYPE_CHECKING, List, Optional

from tools.clumsy_ics import read_clumsy_ics_state

if TYPE_CHECKING:
    from networking.scanner import Scanner

CLUMSY_BUNDLE_FLAG_NAME = 'clumsy_mode_bundle.flag'
_ICS_SUBNET_PREFIX = '192.168.137.'
_LAST_ICS_PING_SWEEP_MONO = 0.0
_ICS_PING_SWEEP_COOLDOWN_SEC = 22.0
_ICS_PING_SWEEP_LAST_OCTET_MAX = 32


def clumsy_bundle_flag_path() -> str:
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.getcwd()
    return os.path.join(base, CLUMSY_BUNDLE_FLAG_NAME)


def clumsy_bundle_offered() -> bool:
    if not sys.platform.startswith('win'):
        return False
    if not getattr(sys, 'frozen', False):
        return True
    return os.path.isfile(clumsy_bundle_flag_path())


def windivert_driver_installed() -> bool:
    """
    WinDivert 2.x: no pnputil — ship WinDivert64.sys (+ WinDivert.dll) with the app.
    Treat as "available" if the signed .sys is bundled next to the exe or already in DriverStore.
    """
    if not sys.platform.startswith('win'):
        return False
    sys_root = os.environ.get('SystemRoot', r'C:\Windows')
    if os.path.isfile(os.path.join(sys_root, 'System32', 'drivers', 'WinDivert64.sys')):
        return True
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.getcwd()
    sub = os.path.join(base, 'windivert', 'WinDivert64.sys')
    if os.path.isfile(sub):
        return True
    return os.path.isfile(os.path.join(base, 'WinDivert64.sys'))


def clumsy_runtime_ready() -> bool:
    if not sys.platform.startswith('win'):
        return False
    if not getattr(sys, 'frozen', False):
        return True
    return clumsy_bundle_offered() and windivert_driver_installed()


def clumsy_mode_enabled() -> bool:
    try:
        from tools.utils_gui import get_settings

        return bool(get_settings('clumsy_mode'))
    except Exception:
        return False


def maybe_prepare_ics() -> None:
    if not sys.platform.startswith('win'):
        return
    try:
        from tools.utils import terminal

        terminal('net start SharedAccess', shell=True)
    except Exception:
        pass


def _arp_lines_for_scanner(scanner: Scanner) -> str:
    try:
        return scanner._windows_arp_raw_text()
    except Exception:
        return ''


def _parse_ics_clients(
    arp_text: str,
    my_ip: str,
    router_ip: str,
    subnet_prefix: str,
    host_ip: str,
) -> List[str]:
    if not arp_text or not arp_text.strip():
        return []
    pat_ip = re.compile(r'\b((?:\d{1,3}\.){3}\d{1,3})\b')
    out: List[str] = []
    seen = set()
    for raw in arp_text.split('\n'):
        line = (raw or '').strip()
        if not line:
            continue
        low = line.lower()
        if 'incomplete' in low:
            continue
        m = pat_ip.search(line)
        if not m:
            continue
        ip = m.group(1)
        if not ip.startswith(subnet_prefix):
            continue
        if ip in (my_ip, router_ip, host_ip):
            continue
        try:
            last = int(ip.rsplit('.', 1)[-1])
        except (ValueError, IndexError):
            continue
        if last <= 1 or last >= 255:
            continue
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    out.sort(key=lambda x: int(x.rsplit('.', 1)[-1]))
    return out


def _ping_sweep_ics_subnet_windows(subnet_prefix: str, skip_ips: set[str]) -> None:
    """Best-effort: ping ICS range so Windows populates ARP for live consoles."""
    if not subnet_prefix.endswith('.'):
        return
    try:
        from tools.utils import terminal
    except Exception:
        return
    for last in range(2, min(_ICS_PING_SWEEP_LAST_OCTET_MAX + 1, 255)):
        ip = f'{subnet_prefix}{last}'
        if ip in skip_ips:
            continue
        try:
            terminal(f'ping -n 1 -w 150 {ip}', decode=False)
        except Exception:
            pass


def _maybe_refresh_ics_clients_via_ping(
    subnet_prefix: str,
    my_ip: str,
    router_ip: str,
    host_ip: str,
) -> None:
    global _LAST_ICS_PING_SWEEP_MONO
    if not sys.platform.startswith('win'):
        return
    now = time.monotonic()
    if now - _LAST_ICS_PING_SWEEP_MONO < _ICS_PING_SWEEP_COOLDOWN_SEC:
        return
    _LAST_ICS_PING_SWEEP_MONO = now
    skip = {x for x in (my_ip, router_ip, host_ip) if x}
    _ping_sweep_ics_subnet_windows(subnet_prefix, skip)


def detect_inline_ip(
    scanner: Scanner,
    *,
    allow_subnet_ping: bool = False,
) -> Optional[str]:
    if not clumsy_runtime_ready() or not clumsy_mode_enabled():
        return None
    maybe_prepare_ics()
    my_ip = (getattr(scanner, 'my_ip', None) or '').strip()
    router_ip = (getattr(scanner, 'router_ip', None) or '').strip()
    state = read_clumsy_ics_state()
    subnet_prefix = str(state.get('downstream_prefix') or '').strip()
    if not subnet_prefix:
        subnet_prefix = _ICS_SUBNET_PREFIX
    host_ip = str(state.get('downstream_ipv4') or '').strip()
    text = _arp_lines_for_scanner(scanner)
    clients = _parse_ics_clients(text, my_ip, router_ip, subnet_prefix, host_ip)
    if not clients and allow_subnet_ping:
        _maybe_refresh_ics_clients_via_ping(subnet_prefix, my_ip, router_ip, host_ip)
        text = _arp_lines_for_scanner(scanner)
        clients = _parse_ics_clients(text, my_ip, router_ip, subnet_prefix, host_ip)
    if not clients:
        return None
    return clients[0]


def sync_clumsy_row(scanner: Scanner, *, allow_subnet_ping: bool = False) -> None:
    """
    Remove legacy synthetic rows; when clumsy mode is on, dedupe duplicate non-admin
    devices that share the detected ICS client IPv4 (keep first list occurrence).
    """
    scanner.devices = [d for d in scanner.devices if not d.get('clumsy_inline')]
    if not clumsy_mode_enabled() or not clumsy_runtime_ready():
        return
    ip = detect_inline_ip(scanner, allow_subnet_ping=allow_subnet_ping)
    if not ip:
        return
    ip_norm = str(ip).strip()
    same = [
        i
        for i, d in enumerate(scanner.devices)
        if not d.get('admin') and str(d.get('ip') or '').strip() == ip_norm
    ]
    if len(same) <= 1:
        return
    keep_mac = scanner.devices[same[0]]['mac']
    scanner.devices = [
        d
        for d in scanner.devices
        if d.get('admin') or str(d.get('ip') or '').strip() != ip_norm or d.get('mac') == keep_mac
    ]


def use_windivert_for_advanced_ics_shaping(scanner: Scanner, device: dict) -> bool:
    """
    True when Advanced shaping should use the WinDivert driver path (Clumsy mode on,
    WinDivert bundle ready, and the target row matches the detected ICS client IPv4).
    """
    if not sys.platform.startswith('win'):
        return False
    if not clumsy_mode_enabled() or not clumsy_runtime_ready():
        return False
    if not isinstance(device, dict) or device.get('admin'):
        return False
    dip = str(device.get('ip') or '').strip()
    if not dip:
        return False
    ip = detect_inline_ip(scanner, allow_subnet_ping=False)
    if not ip:
        return False
    return dip == str(ip).strip()
