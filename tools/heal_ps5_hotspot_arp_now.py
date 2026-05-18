#!/usr/bin/env python3
"""Clear ZubCut blocks and restore PS5/hotspot gateway ARP (run as Administrator)."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

_REPO_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

_GW = '192.168.137.1'
_PREFIX = '192.168.137.'


def _run(cmd: str, *, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            errors='replace',
            timeout=timeout,
        )
        return (r.stdout or '') + (r.stderr or '')
    except Exception as exc:
        return str(exc)


def _hotspot_host_mac() -> str:
    out = _run('getmac /fo csv /nh /v')
    for line in out.splitlines():
        if _GW in line or '137' in line:
            m = re.search(r'([0-9A-Fa-f]{2}([-:])[0-9A-Fa-f]{2}\2){5}[0-9A-Fa-f]{2}', line)
            if m:
                return m.group(0).replace('-', ':').upper()
    out = _run(f'arp -a -N {_GW}')
    for line in out.splitlines():
        if _GW in line:
            m = re.search(r'([0-9a-fA-F]{2}([-:])[0-9a-fA-F]{2}\2){5}[0-9a-fA-F]{2}', line, re.I)
            if m:
                return m.group(0).replace('-', ':').upper()
    try:
        from tools.utils import get_default_iface
        from tools.utils import good_mac

        iface = get_default_iface()
        mac = good_mac(getattr(iface, 'mac', None))
        if mac:
            return mac
    except Exception:
        pass
    return ''


def _arp_clients() -> list[dict]:
    out = _run('arp -a')
    clients: list[dict] = []
    seen: set[str] = set()
    pat = re.compile(
        r'\b(192\.168\.137\.(\d{1,3}))\b\s+'
        r'([0-9a-fA-F]{2}(?:[-:])[0-9a-fA-F]{2}(?:[-:])[0-9a-fA-F]{2}(?:[-:])'
        r'[0-9a-fA-F]{2}(?:[-:])[0-9a-fA-F]{2}(?:[-:])[0-9a-fA-F]{2})\b'
    )
    for line in out.splitlines():
        if 'incomplete' in line.lower():
            continue
        m = pat.search(line)
        if not m:
            continue
        ip = m.group(1)
        last = int(m.group(2))
        if last <= 1 or last >= 255:
            continue
        mac = m.group(3).replace('-', ':').upper()
        if ip not in seen:
            seen.add(ip)
            clients.append({'ip': ip, 'mac': mac})
    return clients


def _ping_sweep() -> None:
    print('Pinging hotspot subnet to find PS5...')
    for last in range(2, 33):
        ip = f'{_PREFIX}{last}'
        _run(f'ping -n 1 -w 200 {ip}', timeout=5)


def _gratuitous_heal(pc_mac: str, clients: list[dict], repeats: int = 4) -> int:
    try:
        from scapy.all import ARP, Ether, sendp
    except ImportError:
        print('scapy not installed — skipping gratuitous ARP (firewall cleanup still applied)')
        return 0

    healed = 0
    gw_mac = pc_mac
    for vic in clients:
        ip = vic['ip']
        vic_mac = vic['mac']
        unicast = (
            Ether(dst=vic_mac)
            / ARP(op=2, psrc=_GW, hwsrc=gw_mac, pdst=ip, hwdst=vic_mac)
        )
        gratuitous = (
            Ether(dst='ff:ff:ff:ff:ff:ff')
            / ARP(op=2, psrc=_GW, hwsrc=gw_mac, pdst=_GW, hwdst='ff:ff:ff:ff:ff:ff')
        )
        for _ in range(repeats):
            sendp([unicast, gratuitous], verbose=0)
        print(f'  Healed gateway ARP -> {ip} ({vic_mac})')
        healed += 1
    return healed


def main() -> int:
    if sys.platform != 'win32':
        print('Windows only')
        return 1

    try:
        import ctypes

        if not ctypes.windll.shell32.IsUserAnAdmin():
            print('Re-launching as Administrator...')
            script = str(Path(__file__).resolve())
            ctypes.windll.shell32.ShellExecuteW(
                None, 'runas', sys.executable, f'"{script}"', None, 1
            )
            return 0
    except Exception:
        pass

    print('=== Heal PS5 hotspot ARP / clear ZubCut blocks ===\n')

    zub = subprocess.run(
        ['tasklist', '/FI', 'IMAGENAME eq ZubCut.exe'],
        capture_output=True,
        text=True,
        errors='replace',
    )
    if 'ZubCut.exe' in (zub.stdout or ''):
        print('Stopping ZubCut so in-memory ARP MITM cannot return...')
        subprocess.run(['taskkill', '/IM', 'ZubCut.exe', '/F'], capture_output=True)
        time.sleep(1.5)

    print('1) Removing stale firewall / WinDivert blocks...')
    try:
        from tools.pfctl import teardown_all_zubcut_network_attacks
        from tools.ics_windivert_shaper import _windivert_sc_stop_and_delete
        from tools.clumsy_ics import purge_clumsy_stale_attack_blocks

        purge_clumsy_stale_attack_blocks()
        summary = teardown_all_zubcut_network_attacks()
        print(f'   Firewall rules removed: {summary.get("firewall_rules_removed", 0)}')
        ips = summary.get('unblocked_ips') or []
        if ips:
            print(f'   Unblocked: {", ".join(ips)}')
        _windivert_sc_stop_and_delete()
        print('   WinDivert service cleared')
    except Exception as exc:
        print(f'   Cleanup warning: {exc}')

    clients = _arp_clients()
    if not clients:
        _ping_sweep()
        time.sleep(0.5)
        clients = _arp_clients()

    print(f'\n2) Hotspot clients on ARP table: {len(clients)}')
    for c in clients:
        print(f'   {c["ip"]}  {c["mac"]}')
    if not clients:
        print(
            '   (none — connect PS5 to hotspot "osps" and run this script again)\n'
            '   Hotspot gateway is still cleared of ZubCut blocks.'
        )
        return 0

    pc_mac = _hotspot_host_mac()
    if not pc_mac:
        print('   Could not detect PC MAC on hotspot — heal skipped')
        return 1

    print(f'\n3) Sending gateway ARP heal (PC {_GW} = {pc_mac})...')
    n = _gratuitous_heal(pc_mac, clients)
    print(f'\nDone. Healed {n} client(s). Test PS5 internet / NAT.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
