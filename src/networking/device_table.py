"""
MAC-centric device table for ZubCut.

Builds the scan table device list for ZubCut. When Clumsy hotspot or
ethernet-console mode is active, one row per MAC (ICS IP preferred). The UI and
``scanner.devices`` use the same dict shape; this module builds and refreshes that list.

Regular home-LAN mode keeps separate rows per subnet profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, List, Optional

from constants import GLOBAL_MAC
from networking.nicknames import (
    Nicknames,
    ipv4_subnet_prefix,
    nickname_profile_key,
    record_nickname_last_ip,
)
from tools.device_display import infer_network_device_type
from tools.utils import good_mac, get_vendor

if TYPE_CHECKING:
    from networking.scanner import Scanner


def clumsy_mac_centric_table() -> bool:
    """One console row per MAC (hotspot / ethernet-console), not per home-LAN subnet."""
    if not __import__('sys').platform.startswith('win'):
        return False
    try:
        from tools.clumsy_inline import clumsy_mode_enabled
        from tools.clumsy_ics import read_clumsy_topology

        if not clumsy_mode_enabled():
            return False
        return read_clumsy_topology() in ('hotspot', 'ethernet')
    except Exception:
        return False


@dataclass
class _ClientEntry:
    mac: str
    lan_ip: str = ''
    ics_ip: str = ''
    vendor: str = ''
    dev_type: str = 'User'
    name: str = '-'

    def absorb_hit(self, ip: str, *, ics_prefix: str) -> None:
        ip = (ip or '').strip()
        if not ip:
            return
        if ics_prefix and ip.startswith(ics_prefix):
            self.ics_ip = ip
        else:
            self.lan_ip = ip

    def display_ip(self, *, mac_centric: bool, ics_prefix: str) -> str:
        if mac_centric:
            return self.ics_ip or self.lan_ip
        if self.ics_ip:
            return self.ics_ip
        return self.lan_ip


def _sort_ip_key(ip: str) -> int:
    try:
        return int(str(ip).rsplit('.', 1)[-1])
    except (ValueError, IndexError, TypeError, AttributeError):
        return 0


def _carry_nickname_to_display_ip(
    nicknames: Nicknames, mac: str, lan_ip: str, display_ip: str
) -> str:
    """If the console moved subnets, reuse the home-LAN nickname on the hotspot row."""
    if not display_ip or display_ip == lan_ip:
        return nicknames.get_name(mac, display_ip or lan_ip)
    name = nicknames.get_name(mac, display_ip)
    if name and name != '-':
        return name
    if lan_ip:
        old = nicknames.get_name(mac, lan_ip)
        if old and old != '-':
            try:
                nicknames.set_name(mac, old, display_ip)
                record_nickname_last_ip(mac, display_ip)
            except Exception:
                pass
            return old
    return nicknames.get_name(mac, display_ip) or '-'


def _ics_prefix() -> str:
    try:
        from tools.clumsy_inline import clumsy_ics_downstream_prefix

        return clumsy_ics_downstream_prefix()
    except Exception:
        return '192.168.137.'


def _is_ics_ip(ip: str, ics_prefix: str) -> bool:
    ip = (ip or '').strip()
    return bool(ip and ics_prefix and ip.startswith(ics_prefix))


def build_client_rows_from_scan(
    scanner: 'Scanner',
    scan_result: Iterable[tuple[str, str]],
) -> List[dict]:
    """
    Build non-admin device dicts from (ip, mac) scan hits.

    MAC-centric in Clumsy hotspot/ethernet; profile-per-subnet otherwise.
    """
    nicknames = Nicknames()
    mac_centric = clumsy_mac_centric_table()
    ics_prefix = _ics_prefix()
    router_ip = (getattr(scanner, 'router_ip', None) or '').strip()
    my_ip = (getattr(scanner, 'my_ip', None) or '').strip()

    hits = sorted(
        ((str(ip).strip(), good_mac(mac)) for ip, mac in scan_result),
        key=lambda x: _sort_ip_key(x[0]),
    )

    if mac_centric:
        by_mac: dict[str, _ClientEntry] = {}
        for ip, mac in hits:
            if not mac or mac == GLOBAL_MAC:
                continue
            if ip in (router_ip, my_ip):
                continue
            ent = by_mac.setdefault(mac, _ClientEntry(mac=mac))
            ent.absorb_hit(ip, ics_prefix=ics_prefix)
        rows: List[dict] = []
        for mac in sorted(by_mac.keys()):
            ent = by_mac[mac]
            if not ent.vendor:
                ent.vendor = get_vendor(mac)
            try:
                ent.dev_type = infer_network_device_type(mac, ent.vendor, '')
            except Exception:
                ent.dev_type = 'User'
            display = ent.display_ip(mac_centric=True, ics_prefix=ics_prefix)
            if not display:
                continue
            ent.name = _carry_nickname_to_display_ip(
                nicknames, mac, ent.lan_ip, display
            )
            rows.append(_entry_to_device_dict(ent, display))
            if ent.name and ent.name != '-':
                record_nickname_last_ip(mac, display)
        return sorted(rows, key=lambda d: _sort_ip_key(d.get('ip', '')))

    # Home LAN: separate row per MAC|subnet profile.
    seen_profiles: set[str] = set()
    rows = []
    for ip, mac in hits:
        if not mac or mac == GLOBAL_MAC:
            continue
        if ip in (router_ip, my_ip):
            continue
        profile = nickname_profile_key(mac, ip)
        if not profile or profile in seen_profiles:
            continue
        seen_profiles.add(profile)
        vend = get_vendor(mac)
        try:
            dev_type = infer_network_device_type(mac, vend, '')
        except Exception:
            dev_type = 'User'
        nm = nicknames.get_name(mac, ip)
        rows.append(
            {
                'ip': ip,
                'mac': mac,
                'vendor': vend,
                'type': dev_type,
                'name': nm,
                'admin': False,
            }
        )
        if nm and nm != '-':
            record_nickname_last_ip(mac, ip)
    return rows


def _entry_to_device_dict(ent: _ClientEntry, display_ip: str) -> dict:
    out = {
        'ip': display_ip,
        'mac': ent.mac,
        'vendor': ent.vendor,
        'type': ent.dev_type,
        'name': ent.name,
        'admin': False,
    }
    if ent.lan_ip and ent.lan_ip != display_ip:
        out['lan_ip'] = ent.lan_ip
    if ent.ics_ip and ent.ics_ip != display_ip:
        out['ics_ip'] = ent.ics_ip
    return out


def refresh_client_ips_from_ics(
    scanner: 'Scanner',
    *,
    allow_subnet_ping: bool = False,
) -> None:
    """
    Update non-admin rows with ICS ARP / inline detection (hotspot path).

    Merges duplicate rows for the same MAC into one row with the best IP.
    """
    try:
        from tools.clumsy_inline import (
            clumsy_hotspot_session_active,
            clumsy_ics_arp_ip_for_mac,
            clumsy_ics_resolve_victim_ip,
            clumsy_mode_enabled,
            clumsy_runtime_ready,
            detect_inline_ip,
            victim_on_clumsy_ics_subnet,
        )
    except Exception:
        return

    if not clumsy_mode_enabled():
        return

    ics_prefix = _ics_prefix()
    mac_centric = clumsy_mac_centric_table()
    inline_ip = ''
    if clumsy_runtime_ready():
        try:
            inline_ip = detect_inline_ip(
                scanner, allow_subnet_ping=allow_subnet_ping
            ) or ''
        except Exception:
            inline_ip = ''
    inline_ip = str(inline_ip).strip()

    admins = [d for d in scanner.devices if d.get('admin')]
    clients = [d for d in scanner.devices if not d.get('admin')]

    if mac_centric:
        by_mac: dict[str, dict] = {}
        nicknames = Nicknames()
        for d in clients:
            mac = good_mac(d.get('mac'))
            if not mac:
                continue
            row = dict(d)
            lan = str(row.get('lan_ip') or '').strip()
            if not lan and not _is_ics_ip(str(row.get('ip') or ''), ics_prefix):
                lan = str(row.get('ip') or '').strip()
            ics = str(row.get('ics_ip') or '').strip()
            if not ics and _is_ics_ip(str(row.get('ip') or ''), ics_prefix):
                ics = str(row.get('ip') or '').strip()
            arp_ip = clumsy_ics_arp_ip_for_mac(scanner, mac)
            if arp_ip:
                ics = arp_ip
            resolved = clumsy_ics_resolve_victim_ip(row, scanner)
            if victim_on_clumsy_ics_subnet(resolved):
                ics = resolved
            display = ics or lan
            if not display:
                continue
            row['ip'] = display
            if lan and lan != display:
                row['lan_ip'] = lan
            if ics and ics != display:
                row['ics_ip'] = ics
            row['name'] = _carry_nickname_to_display_ip(
                nicknames, mac, lan, display
            )
            prev = by_mac.get(mac)
            if prev is None:
                by_mac[mac] = row
            else:
                prev_ics = _is_ics_ip(str(prev.get('ip') or ''), ics_prefix)
                new_ics = _is_ics_ip(display, ics_prefix)
                if new_ics and not prev_ics:
                    by_mac[mac] = row
        clients = sorted(by_mac.values(), key=lambda d: _sort_ip_key(d.get('ip', '')))
    else:
        for row in clients:
            mac = good_mac(row.get('mac'))
            if not mac:
                continue
            resolved = clumsy_ics_resolve_victim_ip(row, scanner)
            if resolved and resolved != row.get('ip'):
                row['ip'] = resolved
                if _is_ics_ip(resolved, ics_prefix):
                    row['ics_ip'] = resolved

        if inline_ip:
            same = [
                d
                for d in clients
                if str(d.get('ip') or '').strip() == inline_ip
            ]
            if len(same) > 1:
                keep_mac = good_mac(same[0].get('mac'))
                clients = [
                    d
                    for d in clients
                    if str(d.get('ip') or '').strip() != inline_ip
                    or good_mac(d.get('mac')) == keep_mac
                ]

    scanner.devices = admins + clients


def phantom_favorite_should_skip(
    scanner: 'Scanner', mac: str, ip: str, present_profiles: set[str]
) -> bool:
    """Skip injecting a stale home-LAN phantom when MAC-centric row already exists."""
    if not clumsy_mac_centric_table():
        return False
    mac = good_mac(mac)
    if not mac:
        return False
    ics_prefix = _ics_prefix()
    home_prefix = ipv4_subnet_prefix(ip)
    ics_net = ipv4_subnet_prefix(ics_prefix.rstrip('.'))
    if home_prefix == ics_net:
        return False
    for d in scanner.devices:
        if d.get('admin'):
            continue
        if good_mac(d.get('mac')) == mac:
            return True
    return False


def extra_scan_hits_from_ics_arp(scanner: 'Scanner') -> List[tuple[str, str]]:
    """
    ICS-subnet (ip, mac) pairs from the OS ARP table for Clumsy hotspot/ethernet scans.

    Merged into easy/hard scan results so the device table is not limited to router /24.
    """
    if not clumsy_mac_centric_table():
        return []
    try:
        from tools.clumsy_inline import (
            _arp_lines_for_scanner,
            _parse_ics_arp_entries,
        )
        from tools.clumsy_ics import read_clumsy_ics_state
    except Exception:
        return []
    ics_prefix = _ics_prefix()
    try:
        state = read_clumsy_ics_state()
        host_ip = str(state.get('downstream_ipv4') or '').strip()
    except Exception:
        host_ip = ''
    my_ip = (getattr(scanner, 'my_ip', None) or '').strip()
    router_ip = (getattr(scanner, 'router_ip', None) or '').strip()
    text = _arp_lines_for_scanner(scanner)
    hits: List[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in _parse_ics_arp_entries(
        text, my_ip, router_ip, ics_prefix, host_ip
    ):
        ip = str(entry.get('ip') or '').strip()
        mac = good_mac(entry.get('mac'))
        if not ip or not mac or mac == GLOBAL_MAC:
            continue
        pair = (ip, mac)
        if pair not in seen:
            seen.add(pair)
            hits.append(pair)
    return hits


def sync_device_table(scanner: 'Scanner', *, allow_subnet_ping: bool = False) -> None:
    """Public entry: refresh ICS IPs and dedupe (replaces legacy ``sync_clumsy_row``)."""
    scanner.devices = [d for d in scanner.devices if not d.get('clumsy_inline')]
    try:
        from tools.clumsy_inline import clumsy_mode_enabled
    except Exception:
        return
    if not clumsy_mode_enabled():
        return
    refresh_client_ips_from_ics(scanner, allow_subnet_ping=allow_subnet_ping)
