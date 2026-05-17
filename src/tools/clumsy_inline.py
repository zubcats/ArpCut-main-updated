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

from constants import GLOBAL_MAC
from tools.clumsy_ics import read_clumsy_ics_state
from tools.utils import good_mac, get_vendor

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


def windivert_app_dir() -> Optional[str]:
    """{app}\\windivert next to ZubCut.exe (installer layout)."""
    if not sys.platform.startswith('win'):
        return None
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.getcwd()
    path = os.path.join(base, 'windivert')
    return path if os.path.isdir(path) else None


def windivert_bundled_next_to_app() -> bool:
    """True when WinDivert.dll and WinDivert64.sys are beside the running app."""
    wd = windivert_app_dir()
    if not wd:
        return False
    return (
        os.path.isfile(os.path.join(wd, 'WinDivert.dll'))
        and os.path.isfile(os.path.join(wd, 'WinDivert64.sys'))
    )


def windivert_driver_installed() -> bool:
    """
    WinDivert 2.x: bundled under {app}\\windivert (installer) or legacy System32 copy.
  """
    if not sys.platform.startswith('win'):
        return False
    if windivert_bundled_next_to_app():
        return True
    sys_root = os.environ.get('SystemRoot', r'C:\Windows')
    if os.path.isfile(os.path.join(sys_root, 'System32', 'drivers', 'WinDivert64.sys')):
        return True
    from tools.ics_windivert_shaper import _windivert_dll_path

    return bool(_windivert_dll_path())


def clumsy_bundle_incomplete() -> bool:
    """Installer offered Clumsy but WinDivert files are missing (broken install)."""
    return clumsy_bundle_offered() and not windivert_bundled_next_to_app()


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


def clumsy_ics_downstream_prefix() -> str:
    state = read_clumsy_ics_state()
    prefix = str(state.get('downstream_prefix') or '').strip()
    if not prefix:
        prefix = _ICS_SUBNET_PREFIX
    if not prefix.endswith('.'):
        prefix += '.'
    return prefix


def victim_on_clumsy_ics_subnet(victim_ip: str) -> bool:
    ip = str(victim_ip or '').strip()
    if not ip:
        return False
    return ip.startswith(clumsy_ics_downstream_prefix())


def clumsy_ics_use_firewall_only(device) -> bool:
    """
    Victim is on the Mobile Hotspot / ICS subnet (e.g. 192.168.137.x).

    Use WinDivert or firewall for block — not home-router ARP MITM. Optional ICS ARP
    kill must use ics_mode on Killer after apply_clumsy_ics_router_context.
    """
    if not clumsy_mode_enabled() or not sys.platform.startswith('win'):
        return False
    if not isinstance(device, dict):
        return False
    return victim_on_clumsy_ics_subnet(str(device.get('ip') or ''))


def clumsy_ics_lag_can_use_windivert(device) -> bool:
    """WinDivert path for all ICS lag (Kill, Dupe, Advanced Lag, Percent Cut, etc.)."""
    if not clumsy_ics_use_firewall_only(device):
        return False
    if not clumsy_runtime_ready():
        return False
    from tools.ics_windivert_shaper import _windivert_dll_path

    return bool(_windivert_dll_path())


def clumsy_windivert_unavailable_reason(device) -> str:
    """Short reason WinDivert ICS lag is unavailable (for logs / settings)."""
    if not sys.platform.startswith('win'):
        return 'Windows only'
    if not clumsy_mode_enabled():
        return 'enable Clumsy mode in Settings and restart ZubCut'
    if getattr(sys, 'frozen', False) and not clumsy_bundle_offered():
        return 'reinstall with Clumsy mode checked (WinDivert bundle)'
    if not windivert_bundled_next_to_app():
        return 'WinDivert.dll missing next to ZubCut.exe (reinstall or repair)'
    if not isinstance(device, dict):
        return 'no device selected'
    ip = str(device.get('ip') or '').strip()
    if not ip:
        return 'target has no IP yet'
    if not victim_on_clumsy_ics_subnet(ip):
        prefix = clumsy_ics_downstream_prefix()
        return f'target {ip} is not on hotspot subnet {prefix}x'
    return 'unknown'


def apply_ics_victim_arp_block(scanner: Scanner, killer, device) -> bool:
    """
    Hotspot kill/lag: ARP toward the console only (same red Wi‑Fi icon as normal ZubCut).

    Uses gateway 192.168.137.1 — not home-router ARP MITM. Skips flush_arp (Clumsy mode).
    """
    if not clumsy_ics_use_firewall_only(device):
        return False
    if not isinstance(device, dict):
        return False
    ip = str(device.get('ip') or '').strip()
    mac = str(device.get('mac') or '').strip()
    if not ip or not mac:
        return False
    try:
        scanner.sync_iface_for_victim_ip(ip)
    except Exception:
        pass
    apply_clumsy_ics_router_context(scanner, killer, ip)
    killer.iface = scanner.iface
    killer.router = scanner.router
    try:
        killer._close_socket()
    except Exception:
        pass
    try:
        killer.disable_percent_cut(mac)
        killer.kill(device, ics_mode=True)
        return True
    except Exception:
        return False


def release_ics_victim_block(scanner: Scanner, killer, victim) -> bool:
    """
    Tear down ICS ARP MITM only when it was started (killer.killed).

    WinDivert-only lag/dupe/kill must not run reinforce_restore/heal — that adds
    seconds of stray ARP and makes the PS5 look offline long after OFF.
    """
    if not isinstance(victim, dict):
        return False
    ip = str(victim.get('ip') or '').strip()
    mac = str(victim.get('mac') or '').strip()
    if not victim_on_clumsy_ics_subnet(ip) or not mac:
        return False
    if mac not in killer.killed:
        return False
    try:
        apply_clumsy_ics_router_context(scanner, killer, ip)
        killer.iface = scanner.iface
        killer.router = scanner.router
        killer.unkill(victim, ics_mode=True)
        heal_ics_client_after_mitm(scanner, killer, victim)
        return True
    except Exception:
        return False


def apply_clumsy_ics_router_context(scanner: Scanner, killer, victim_ip: str) -> bool:
    """
    On ICS/hotspot, the console's gateway is this PC (e.g. 192.168.137.1), not the home router.

    After sync_iface_for_victim_ip, refresh_local_topology may set router_ip to 192.168.1.1
    from the wrong route table; ARP MITM then breaks hotspot internet for everyone.
    """
    if not clumsy_mode_enabled() or not sys.platform.startswith('win'):
        return False
    if not victim_on_clumsy_ics_subnet(victim_ip):
        return False
    prefix = clumsy_ics_downstream_prefix()
    gw = str(read_clumsy_ics_state().get('downstream_ipv4') or '').strip()
    if not gw or not gw.startswith(prefix.rstrip('.')):
        gw = prefix.rstrip('.') + '.1'
    my_mac = good_mac(getattr(scanner.iface, 'mac', None) or GLOBAL_MAC)
    router = {
        'ip': gw,
        'mac': my_mac,
        'vendor': get_vendor(my_mac),
        'type': 'Router',
        'name': '',
        'admin': True,
    }
    scanner.router_ip = gw
    scanner.router_mac = my_mac
    scanner.router = router
    for row in scanner.devices:
        if row.get('type') == 'Router':
            row['ip'] = gw
            row['mac'] = my_mac
            row['vendor'] = get_vendor(my_mac)
    killer.router = router
    killer.iface = scanner.iface
    return True


def heal_ics_client_after_mitm(scanner: Scanner, killer, victim: dict, *, repeats: int = 2) -> bool:
    """
    After lag/kill on a hotspot client, the console may keep a stale ARP entry for the
    gateway (192.168.137.1). PS5 "automatic IP" fix is DHCP renew; gratuitous ARP helps
    relearn the gateway MAC without user action.
    """
    if not sys.platform.startswith('win'):
        return False
    ip = str((victim or {}).get('ip') or '').strip()
    if not victim_on_clumsy_ics_subnet(ip):
        return False
    apply_clumsy_ics_router_context(scanner, killer, ip)
    vic_mac = good_mac((victim or {}).get('mac'))
    if not vic_mac:
        return False
    gw = str(scanner.router_ip or '').strip()
    pc_mac = good_mac(scanner.router_mac or getattr(scanner.iface, 'mac', None))
    if not gw or not pc_mac:
        return False
    try:
        from scapy.all import ARP, Ether
    except Exception:
        return False
    unicast = (
        Ether(dst=vic_mac)
        / ARP(
            op=2,
            psrc=gw,
            hwsrc=pc_mac,
            pdst=ip,
            hwdst=vic_mac,
        )
    )
    gratuitous = (
        Ether(dst='ff:ff:ff:ff:ff:ff')
        / ARP(
            op=2,
            psrc=gw,
            hwsrc=pc_mac,
            pdst=gw,
            hwdst='ff:ff:ff:ff:ff:ff',
        )
    )
    n = max(1, min(6, int(repeats)))
    for _ in range(n):
        try:
            killer._send_packet(unicast)
            killer._send_packet(gratuitous)
        except Exception:
            pass
    return True


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

    When allow_subnet_ping is True, may run many sequential pings on the ICS subnet
    to populate ARP — call only from a worker thread (e.g. scan thread), not the Qt GUI thread.
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
