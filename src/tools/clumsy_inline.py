"""
Clumsy mode: optional Windows row for a downstream host on shared Ethernet (ICS subnet).

Detection is best-effort (common ICS range 192.168.137.0/24). MAC/vendor may be unknown.
"""
from __future__ import annotations

import os
import re
import sys
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from constants import CLUMSY_INLINE_MAC

if TYPE_CHECKING:
    from networking.scanner import Scanner

CLUMSY_BUNDLE_FLAG_NAME = 'clumsy_mode_bundle.flag'
_ICS_SUBNET_PREFIX = '192.168.137.'


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


def _parse_ics_clients(arp_text: str, my_ip: str, router_ip: str) -> List[str]:
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
        if not ip.startswith(_ICS_SUBNET_PREFIX):
            continue
        if ip in (my_ip, router_ip, '192.168.137.1'):
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


def detect_inline_ip(scanner: Scanner) -> Optional[str]:
    if not clumsy_runtime_ready() or not clumsy_mode_enabled():
        return None
    maybe_prepare_ics()
    my_ip = (getattr(scanner, 'my_ip', None) or '').strip()
    router_ip = (getattr(scanner, 'router_ip', None) or '').strip()
    text = _arp_lines_for_scanner(scanner)
    clients = _parse_ics_clients(text, my_ip, router_ip)
    if not clients:
        return None
    return clients[0]


def build_inline_device(ip: Optional[str]) -> Dict[str, Any]:
    label_ip = ip if ip else ''
    return {
        'ip': label_ip,
        'mac': CLUMSY_INLINE_MAC,
        'vendor': '',
        'type': 'Ethernet (inline)',
        'name': 'Clumsy target' if ip else 'Clumsy (detecting…)',
        'admin': False,
        'clumsy_inline': True,
    }


def sync_clumsy_row(scanner: Scanner) -> None:
    scanner.devices = [d for d in scanner.devices if not d.get('clumsy_inline')]
    if not clumsy_mode_enabled() or not clumsy_runtime_ready():
        return
    ip = detect_inline_ip(scanner)
    dev = build_inline_device(ip)
    insert_at = 2
    if insert_at > len(scanner.devices):
        insert_at = len(scanner.devices)
    scanner.devices.insert(insert_at, dev)
