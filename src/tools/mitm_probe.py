"""Detect when ARP MITM is armed but victim traffic never reaches the PC NIC."""
from __future__ import annotations

import sys


def iface_is_wireless(iface) -> bool:
    name = str(getattr(iface, 'name', None) or '').lower()
    if any(token in name for token in ('wi-fi', 'wifi', 'wlan', 'wireless', '802.11')):
        return True
    guid = str(getattr(iface, 'guid', None) or '').lower()
    return 'wifi' in guid or 'wlan' in guid


def count_victim_ip_packets(iface_guid: str, victim_ip: str, seconds: float = 1.0) -> int:
    """Return number of IP frames to/from victim_ip seen on iface (0 = MITM likely ineffective)."""
    victim_ip = str(victim_ip or '').strip()
    iface_guid = str(iface_guid or '').strip()
    if not victim_ip or not iface_guid:
        return 0
    try:
        from scapy.all import sniff
    except Exception:
        return -1
    try:
        pkts = sniff(
            filter=f'host {victim_ip}',
            iface=iface_guid,
            timeout=max(0.2, float(seconds)),
            store=True,
        )
        return len(pkts or [])
    except Exception:
        return -1


def mitm_path_warning(iface, victim_ip: str) -> str:
    """User-facing hint when MITM probe sees zero victim traffic."""
    victim_ip = str(victim_ip or '').strip()
    iface_name = str(getattr(iface, 'name', None) or 'this adapter')
    return (
        f'MITM armed on {iface_name} but no traffic from {victim_ip} reached this PC. '
        'Poison is not landing on the live adapter — confirm Settings is the NIC '
        'Windows is using, restart Npcap, then rescan and Kill again.'
    )
