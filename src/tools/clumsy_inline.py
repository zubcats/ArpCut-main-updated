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


def windivert_bundle_complete() -> bool:
    """WinDivert.dll and WinDivert64.sys under {app}\\windivert (installer layout)."""
    try:
        from tools.ics_windivert_shaper import _windivert_install_paths

        dll, sys_p = _windivert_install_paths()
        return bool(dll and sys_p)
    except Exception:
        return windivert_bundled_next_to_app()


def windivert_driver_installed() -> bool:
    """
    WinDivert 2.x: bundled under {app}\\windivert (installer) or legacy System32 copy.
    """
    if not sys.platform.startswith('win'):
        return False
    if windivert_bundle_complete():
        return True
    sys_root = os.environ.get('SystemRoot', r'C:\Windows')
    return os.path.isfile(os.path.join(sys_root, 'System32', 'drivers', 'WinDivert64.sys'))


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


def clumsy_ics_downstream_ifidx() -> int:
    """WinDivert ifIdx for the Mobile Hotspot / ICS downstream adapter, or 0."""
    if not sys.platform.startswith('win'):
        return 0
    cached = getattr(clumsy_ics_downstream_ifidx, '_cached_idx', None)
    if isinstance(cached, int) and cached > 0:
        return cached
    idx = 0
    try:
        from tools.utils import terminal

        state = read_clumsy_ics_state()
        guid = str(state.get('downstream_guid') or '').strip().strip('{}')
        name = str(state.get('downstream_name') or '').strip()
        attempts: list[str] = []
        if guid:
            attempts.append(
                f'powershell -NoProfile -Command '
                f'"(Get-NetAdapter -InterfaceGuid \'{guid}\' -ErrorAction SilentlyContinue).ifIndex"'
            )
        if name:
            safe = name.replace("'", "''")
            attempts.append(
                f'powershell -NoProfile -Command '
                f'"(Get-NetAdapter -Name \'{safe}\' -ErrorAction SilentlyContinue).ifIndex"'
            )
            attempts.append(
                f'powershell -NoProfile -Command '
                f'"(Get-NetAdapter | Where-Object {{ $_.Name -eq \'{safe}\' }} '
                f'| Select-Object -First 1).ifIndex"'
            )
        for cmd in attempts:
            out = (terminal(cmd) or '').strip()
            if not out:
                continue
            try:
                idx = int(out.split()[0])
            except ValueError:
                continue
            if idx > 0:
                break
        if idx <= 0 and name:
            listing = terminal('netsh interface ipv4 show interfaces') or ''
            name_low = name.lower()
            for line in listing.splitlines():
                if name_low not in line.lower():
                    continue
                parts = line.split()
                if parts and parts[0].isdigit():
                    idx = int(parts[0])
                    break
    except Exception:
        idx = 0
    if idx > 0:
        clumsy_ics_downstream_ifidx._cached_idx = idx
    return idx if idx > 0 else 0


def victim_on_clumsy_ics_subnet(victim_ip: str) -> bool:
    ip = str(victim_ip or '').strip()
    if not ip:
        return False
    return ip.startswith(clumsy_ics_downstream_prefix())


def hotspot_arp_cache_sensitive(scanner: Optional['Scanner'] = None) -> bool:
    """
    True when flushing the whole ARP cache can break PS5/hotspot gateway reachability.

    Clumsy mode and active ICS (192.168.137.x host) both qualify.
    """
    if clumsy_mode_enabled():
        return True
    prefix = clumsy_ics_downstream_prefix()
    if scanner is not None:
        my_ip = str(getattr(scanner, 'my_ip', None) or '').strip()
        if my_ip.startswith(prefix):
            return True
    try:
        state = read_clumsy_ics_state()
        gw = str(state.get('downstream_ipv4') or '').strip()
        if gw.startswith(prefix.rstrip('.')):
            return True
    except Exception:
        pass
    return False


def clumsy_ics_resolve_victim_ip(device, scanner: Optional['Scanner'] = None) -> str:
    """
    Best IPv4 for ICS lag when the device table still shows the home LAN (e.g. 192.168.1.x)
    but the console is on the PC hotspot (192.168.137.x).
    """
    ip = str((device or {}).get('ip') or '').strip()
    if victim_on_clumsy_ics_subnet(ip):
        return ip
    if not clumsy_mode_enabled() or not isinstance(device, dict):
        return ip
    mac = good_mac(device.get('mac'))
    if not mac or mac == GLOBAL_MAC:
        return ip
    prefix = clumsy_ics_downstream_prefix()
    try:
        from tools.utils import terminal

        state = read_clumsy_ics_state()
        gw = str(state.get('downstream_ipv4') or '').strip()
        caches: list[str] = []
        if gw:
            caches.append(terminal(f'arp -a -N {gw}') or '')
        if scanner is not None:
            my = (getattr(scanner, 'my_ip', None) or '').strip()
            if my and my.startswith(prefix):
                caches.append(terminal(f'arp -a -N {my}') or '')
        caches.append(terminal('arp -a') or '')
        mac_needle = mac.lower()
        seen: set[str] = set()
        for cache in caches:
            if not cache or cache in seen:
                continue
            seen.add(cache)
            for line in cache.splitlines():
                if prefix not in line or mac_needle not in line.lower().replace('-', ':'):
                    continue
                for part in line.split():
                    if part.startswith(prefix) and re.match(
                        r'^\d{1,3}(?:\.\d{1,3}){3}$', part
                    ):
                        return part.strip()
    except Exception:
        pass
    return ip


def clumsy_ics_use_firewall_only(device, scanner: Optional['Scanner'] = None) -> bool:
    """
    Victim is on the Mobile Hotspot / ICS subnet (e.g. 192.168.137.x).

    Use WinDivert or firewall for block — not home-router ARP MITM. Optional ICS ARP
    kill must use ics_mode on Killer after apply_clumsy_ics_router_context.
    """
    if not clumsy_mode_enabled() or not sys.platform.startswith('win'):
        return False
    if not isinstance(device, dict):
        return False
    return victim_on_clumsy_ics_subnet(clumsy_ics_resolve_victim_ip(device, scanner))


def clumsy_ics_lag_can_use_windivert(device, scanner: Optional['Scanner'] = None) -> bool:
    """WinDivert path for all ICS lag (Kill, Dupe, Advanced Lag, Percent Cut, etc.)."""
    if not clumsy_ics_use_firewall_only(device, scanner):
        return False
    if not clumsy_runtime_ready():
        return False
    return windivert_bundle_complete()


def _process_is_elevated() -> bool:
    if not sys.platform.startswith('win'):
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def clumsy_windivert_unavailable_reason(device) -> str:
    """Short reason WinDivert ICS lag is unavailable (for logs / settings)."""
    if not sys.platform.startswith('win'):
        return 'Windows only'
    if not clumsy_mode_enabled():
        return 'enable Clumsy mode in Settings and restart ZubCut'
    if not _process_is_elevated():
        return 'run ZubCut as Administrator'
    if getattr(sys, 'frozen', False) and not clumsy_bundle_offered():
        return 'reinstall with Clumsy mode checked (WinDivert bundle)'
    if not windivert_bundle_complete():
        return 'WinDivert.dll + WinDivert64.sys missing in ZubCut\\windivert (reinstall Clumsy mode)'
    if not isinstance(device, dict):
        return 'no device selected'
    ip = clumsy_ics_resolve_victim_ip(device)
    if not ip:
        return 'target has no IP yet'
    if not victim_on_clumsy_ics_subnet(ip):
        prefix = clumsy_ics_downstream_prefix()
        return f'target {ip} is not on hotspot subnet {prefix}x'
    return 'WinDivert could not start (run as Administrator)'


def clumsy_windivert_probe_detail(victim_ip: str) -> str:
    """Live WinDivertOpen test — use in error logs after a failed kill/dupe."""
    if not _process_is_elevated():
        return 'run ZubCut as Administrator (WinDivert requires elevation)'
    try:
        from tools.ics_windivert_shaper import probe_windivert_for_victim

        _ok, detail = probe_windivert_for_victim(victim_ip)
        return detail
    except Exception as exc:
        return str(exc)


def apply_ics_victim_arp_block(scanner: Scanner, killer, device) -> bool:
    """
    Hotspot kill/lag: ARP toward the console only (same red Wi‑Fi icon as normal ZubCut).

    Uses gateway 192.168.137.1 — not home-router ARP MITM. Skips flush_arp (Clumsy mode).
    """
    if not clumsy_ics_use_firewall_only(device):
        return False
    if not isinstance(device, dict):
        return False
    mac = str(device.get('mac') or '').strip()
    ip = clumsy_ics_resolve_victim_ip(device, scanner) or str(
        device.get('ip') or ''
    ).strip()
    if not ip or not mac or not victim_on_clumsy_ics_subnet(ip):
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
        dev = dict(device)
        dev['ip'] = ip
        killer.kill(dev, ics_mode=True)
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
    mac = str(victim.get('mac') or '').strip()
    ip = clumsy_ics_resolve_victim_ip(victim, scanner) or str(
        victim.get('ip') or ''
    ).strip()
    if not victim_on_clumsy_ics_subnet(ip) or not mac:
        return False
    if mac not in killer.killed:
        return False
    try:
        apply_clumsy_ics_router_context(scanner, killer, ip)
        killer.iface = scanner.iface
        killer.router = scanner.router
        v = dict(victim)
        v['ip'] = ip
        killer.unkill(v, ics_mode=True)
        heal_ics_client_after_mitm(scanner, killer, v)
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


def heal_all_hotspot_arp_clients(
    scanner: 'Scanner',
    killer,
    *,
    allow_subnet_ping: bool = False,
    repeats: int = 3,
) -> int:
    """
    Re-teach hotspot clients the PC gateway MAC without ``arp -d *``.

    Use after teardown, startup, or a crashed session that left poisoned ARP on the PS5.
    """
    if not sys.platform.startswith('win'):
        return 0
    prefix = clumsy_ics_downstream_prefix()
    if not prefix.endswith('.'):
        prefix += '.'
    gw = str(read_clumsy_ics_state().get('downstream_ipv4') or '').strip()
    if not gw or not gw.startswith(prefix.rstrip('.')):
        gw = prefix.rstrip('.') + '.1'
    try:
        apply_clumsy_ics_router_context(scanner, killer, gw)
    except Exception:
        pass
    my_ip = (getattr(scanner, 'my_ip', None) or '').strip()
    router_ip = (getattr(scanner, 'router_ip', None) or gw).strip()
    host_ip = gw
    text = _arp_lines_for_scanner(scanner)
    entries = _parse_ics_arp_entries(text, my_ip, router_ip, prefix, host_ip)
    if not entries and allow_subnet_ping:
        _maybe_refresh_ics_clients_via_ping(prefix, my_ip, router_ip, host_ip)
        text = _arp_lines_for_scanner(scanner)
        entries = _parse_ics_arp_entries(text, my_ip, router_ip, prefix, host_ip)
    healed = 0
    for vic in entries:
        try:
            if heal_ics_client_after_mitm(scanner, killer, vic, repeats=repeats):
                healed += 1
        except Exception:
            pass
    return healed


def restore_ics_hotspot_connectivity(
    scanner: 'Scanner',
    killer,
    victim: dict,
    *,
    repeats: int = 4,
) -> bool:
    """
    After dupe/kill/lag on hotspot: bind the hotspot NIC, fix router context, relearn gateway ARP.
    Clumsy only touches packets; we must also undo any stray ARP MITM and refresh the PS5 gateway.
    """
    if not isinstance(victim, dict):
        return False
    ip = clumsy_ics_resolve_victim_ip(victim, scanner)
    if not victim_on_clumsy_ics_subnet(ip):
        return False
    try:
        scanner.sync_iface_for_victim_ip(ip)
    except Exception:
        pass
    apply_clumsy_ics_router_context(scanner, killer, ip)
    vic = dict(victim)
    vic['ip'] = ip
    return heal_ics_client_after_mitm(scanner, killer, vic, repeats=repeats)


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
    return [
        e['ip']
        for e in _parse_ics_arp_entries(arp_text, my_ip, router_ip, subnet_prefix, host_ip)
    ]


def _parse_ics_arp_entries(
    arp_text: str,
    my_ip: str,
    router_ip: str,
    subnet_prefix: str,
    host_ip: str,
) -> List[dict]:
    if not arp_text or not arp_text.strip():
        return []
    if not subnet_prefix.endswith('.'):
        subnet_prefix = subnet_prefix + '.'
    pat = re.compile(
        r'\b((?:\d{1,3}\.){3}\d{1,3})\b\s+'
        r'([0-9a-fA-F]{2}(?:[-:])[0-9a-fA-F]{2}(?:[-:])[0-9a-fA-F]{2}(?:[-:])'
        r'[0-9a-fA-F]{2}(?:[-:])[0-9a-fA-F]{2}(?:[-:])[0-9a-fA-F]{2})\b'
    )
    out: List[dict] = []
    seen = set()
    for raw in arp_text.split('\n'):
        line = (raw or '').strip()
        if not line:
            continue
        low = line.lower()
        if 'incomplete' in low:
            continue
        m = pat.search(line)
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
        mac = good_mac(m.group(2))
        if not mac or mac == GLOBAL_MAC:
            continue
        if ip not in seen:
            seen.add(ip)
            out.append({'ip': ip, 'mac': mac})
    out.sort(key=lambda x: int(x['ip'].rsplit('.', 1)[-1]))
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
    True when Advanced Lag should use WinDivert (hotspot / ICS client).

    Uses the same eligibility as Kill/Lag Switch — any ICS-subnet victim with WinDivert
    ready. Do not require ``detect_inline_ip`` to match (that wrongly forced ARP MITM
    forwarder / Kill-like behavior when ARP listed a different client first).
    """
    return clumsy_ics_lag_can_use_windivert(device, scanner)
