#!/usr/bin/env python3
"""Remove stale ZubCut Kill/Dupe/Lag blocks (firewall + WinDivert). Safe to run with ZubCut closed."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_REPO_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))


def _hotspot_client_ips() -> list[str]:
    ips: set[str] = set()
    try:
        out = subprocess.check_output(['arp', '-a'], text=True, errors='replace', timeout=15)
    except Exception:
        return []
    for line in out.splitlines():
        m = re.search(r'\b(192\.168\.137\.(\d{1,3}))\b', line)
        if not m:
            continue
        ip = m.group(1)
        if ip.endswith('.255') or ip.endswith('.1'):
            continue
        ips.add(ip)
    return sorted(ips)


def main() -> int:
    from tools.pfctl import teardown_all_zubcut_network_attacks, windows_purge_all_zubcut_attack_rules
    from tools.ics_windivert_shaper import _windivert_sc_stop_and_delete

    extra = _hotspot_client_ips()
    print('Hotspot clients (ARP 192.168.137.x):', extra or '(none — PS5 may be disconnected)')

    summary = teardown_all_zubcut_network_attacks(extra_ips=extra)
    removed = int(summary.get('firewall_rules_removed') or 0)
    unblocked = summary.get('unblocked_ips') or []
    print(f'Firewall attack rules removed: {removed}')
    if unblocked:
        print('Unblocked IPs:', ', '.join(unblocked))

    _windivert_sc_stop_and_delete()
    print('WinDivert service: stopped/removed (stale lag/kill gate)')

    # Second pass — catch rules teardown missed
    extra_removed = windows_purge_all_zubcut_attack_rules()
    if extra_removed:
        print(f'Additional attack rules removed: {extra_removed}')

    # Remaining zubcut rules (should be DHCP helpers only)
    res = subprocess.run(
        ['netsh', 'advfirewall', 'firewall', 'show', 'rule', 'name=all'],
        capture_output=True,
        text=True,
        timeout=120,
    )
    attack_left: list[str] = []
    for line in (res.stdout or '').splitlines():
        m = re.match(r'^\s*Rule Name:\s+(zubcut.+)$', line.strip(), re.I)
        if not m:
            continue
        name = m.group(1).strip()
        nl = name.lower()
        if nl.startswith('zubcut_ip_') or nl.startswith('zubcut_block_') or nl.startswith('zubcut_port_'):
            attack_left.append(name)
        elif 'block' in nl and 'dhcp' not in nl and 'hotspot-lan' not in nl:
            if any(x in nl for x in ('kill', 'dupe', 'lag', '_to_')):
                attack_left.append(name)
    if attack_left:
        print('WARNING: attack-like rules still present:', attack_left[:20])
        return 1
    print('OK: no stale ZubCut IP/port block rules remain')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
