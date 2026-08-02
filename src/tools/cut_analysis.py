"""Deep cut Analysis — before / during / after victim + ZubCut-host checks.

Phases (never on the instant-cut hot path):
  BEFORE  — baseline while Analysis is ON (rolling) or frozen at flow start
  DURING  — after Kill/Lag/Dupe/% Cut arm
  AFTER   — after flow OFF / restore

Overall SUCCESS only when the intended full cut is proven; any phase failure
or PARTIAL cut marks the run FAIL. Writes one privacy-masked report under
Desktop\\ZubCut Diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PHASE_BEFORE = 'BEFORE'
PHASE_DURING = 'DURING'
PHASE_AFTER = 'AFTER'


@dataclass
class PhaseSample:
    phase: str
    sample: Dict[str, Any] = field(default_factory=dict)
    host: Dict[str, Any] = field(default_factory=dict)
    stack: Dict[str, Any] = field(default_factory=dict)
    note: str = ''


@dataclass
class PhaseResult:
    phase: str
    passed: bool
    failures: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class CutAnalysisReport:
    flow: str
    verdict: str  # FULL CUT | PARTIAL | NOT CUT | INCONCLUSIVE
    overall: str  # SUCCESS | FAIL
    victim_ip: str
    victim_mac: str
    lines: List[str] = field(default_factory=list)
    report_path: Optional[str] = None
    phases: Dict[str, PhaseSample] = field(default_factory=dict)
    phase_results: Dict[str, PhaseResult] = field(default_factory=dict)

    @property
    def summary_line(self) -> str:
        return (
            f'Analysis [{self.flow}]: {self.overall} ({self.verdict}) — '
            f'{self.victim_ip or "?"} ({self.victim_mac or "no MAC"})'
        )


def _norm_mac(mac: str) -> str:
    return str(mac or '').strip().lower().replace('-', ':')


def _is_lan_ipv4(ip: str) -> bool:
    """True for RFC1918 / link-local / loopback — not proof of internet path."""
    s = str(ip or '').strip()
    if not s:
        return True
    try:
        parts = [int(x) for x in s.split('.')]
        if len(parts) != 4 or any(p < 0 or p > 255 for p in parts):
            return True
    except Exception:
        return True
    a, b = parts[0], parts[1]
    if a == 10 or a == 127 or a == 0:
        return True
    if a == 192 and b == 168:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 169 and b == 254:
        return True
    if a == 100 and 64 <= b <= 127:  # CGNAT — treat as WAN-ish but still "internet-facing"
        return False
    return False


def _is_wan_ipv4(ip: str) -> bool:
    return bool(ip) and not _is_lan_ipv4(ip)


def _sniff_cut_sample(
    iface_guid: str,
    victim_ip: str,
    *,
    seconds: float = 1.5,
    local_mac: str = '',
    gateway_ip: str = '',
    gateway_mac: str = '',
    victim_mac: str = '',
) -> dict[str, Any]:
    """Capture a short sample focused on the *victim's* path, not ZubCut-local view.

    Key counters:
      victim_wan_out_to_us — victim → our MAC, dest is public (WAN attempt via MITM)
      victim_wan_bypass_gw — victim → real gateway MAC, dest public (NOT severed)
      wan_return_bypass    — public → victim via gateway MAC (internet still reaches them)
      poison_arp_seen      — ARP claiming gateway IP is at our MAC
      victim_to_us         — any IPv4 involving victim delivered to our MAC
    """
    out: dict[str, Any] = {
        'ok': False,
        'error': '',
        'ipv4': 0,
        'ipv6': 0,
        'arp': 0,
        'arp_victim': 0,
        'poison_arp_seen': 0,
        'victim_to_us': 0,
        'victim_wan_out_to_us': 0,
        'victim_wan_bypass_gw': 0,
        'wan_return_bypass': 0,
        'victim_lan_ipv4': 0,
        'total': 0,
        'seconds': float(seconds),
    }
    victim_ip = str(victim_ip or '').strip()
    iface_guid = str(iface_guid or '').strip()
    local_mac_n = _norm_mac(local_mac)
    gateway_mac_n = _norm_mac(gateway_mac)
    victim_mac_n = _norm_mac(victim_mac)
    gateway_ip = str(gateway_ip or '').strip()
    if not victim_ip or not iface_guid:
        out['error'] = 'missing iface or victim IP'
        return out
    try:
        from scapy.all import ARP, Ether, IP, IPv6, sniff  # type: ignore
    except Exception as exc:
        out['error'] = f'scapy unavailable: {exc}'
        return out
    bpf = f'arp or host {victim_ip} or ip6'
    try:
        pkts = sniff(
            filter=bpf,
            iface=iface_guid,
            timeout=max(0.4, float(seconds)),
            store=True,
        )
    except Exception as exc:
        out['error'] = f'sniff failed: {exc}'
        return out
    out['ok'] = True
    out['total'] = len(pkts or [])
    vip = victim_ip
    for pkt in pkts or []:
        try:
            if pkt.haslayer(ARP):
                out['arp'] += 1
                arp = pkt[ARP]
                psrc = str(getattr(arp, 'psrc', '') or '')
                pdst = str(getattr(arp, 'pdst', '') or '')
                hwsrc = _norm_mac(str(getattr(arp, 'hwsrc', '') or ''))
                if vip in (psrc, pdst):
                    out['arp_victim'] += 1
                # Poison on wire: "gateway IP is at our MAC"
                if (
                    gateway_ip
                    and local_mac_n
                    and psrc == gateway_ip
                    and hwsrc == local_mac_n
                ):
                    out['poison_arp_seen'] += 1
                continue
            if pkt.haslayer(IPv6):
                out['ipv6'] += 1
                continue
            out['ipv4'] += 1
            if not (pkt.haslayer(Ether) and pkt.haslayer(IP)):
                continue
            eth_src = _norm_mac(str(getattr(pkt[Ether], 'src', '') or ''))
            eth_dst = _norm_mac(str(getattr(pkt[Ether], 'dst', '') or ''))
            src_ip = str(getattr(pkt[IP], 'src', '') or '')
            dst_ip = str(getattr(pkt[IP], 'dst', '') or '')
            involves_victim = vip in (src_ip, dst_ip) or (
                bool(victim_mac_n) and victim_mac_n in (eth_src, eth_dst)
            )
            if not involves_victim:
                continue
            if local_mac_n and eth_dst == local_mac_n:
                out['victim_to_us'] += 1
            # Victim LAN chatter (not internet proof).
            if _is_lan_ipv4(src_ip) and _is_lan_ipv4(dst_ip):
                out['victim_lan_ipv4'] += 1
            # Victim outbound toward the internet.
            from_victim = src_ip == vip or (victim_mac_n and eth_src == victim_mac_n)
            to_victim = dst_ip == vip or (victim_mac_n and eth_dst == victim_mac_n)
            if from_victim and _is_wan_ipv4(dst_ip):
                if local_mac_n and eth_dst == local_mac_n:
                    # Victim thinks we are the gateway — WAN attempt is in our hands.
                    out['victim_wan_out_to_us'] += 1
                elif gateway_mac_n and eth_dst == gateway_mac_n:
                    # Victim still sends WAN traffic straight to the real router = NOT severed.
                    out['victim_wan_bypass_gw'] += 1
                elif local_mac_n and eth_dst != local_mac_n:
                    # Destined elsewhere at L2 while going WAN — treat as bypass.
                    out['victim_wan_bypass_gw'] += 1
            # Internet replies still landing on victim via real gateway (around MITM).
            if (
                to_victim
                and _is_wan_ipv4(src_ip)
                and victim_mac_n
                and eth_dst == victim_mac_n
                and local_mac_n
                and eth_src != local_mac_n
            ):
                if not gateway_mac_n or eth_src == gateway_mac_n:
                    out['wan_return_bypass'] += 1
        except Exception:
            continue
    return out


def probe_victim_on_lan(
    victim_ip: str,
    victim_mac: str = '',
    *,
    iface_ip: str = '',
    arp_probe_iface: str = '',
) -> Dict[str, Any]:
    """
    Prove the selected victim is actually on the LAN right now.

    Stale table rows (old wired IP while PS5 is on Wi‑Fi) must not score as FULL CUT
    just because ZubCut armed MITM/forwarder against a ghost address.
    Uses the same live-endpoint checks as Kill MITM (`victim_endpoint_live_for_mitm`).
    """
    out: Dict[str, Any] = {
        'victim_ping_ok': None,
        'victim_in_arp': None,
        'victim_arp_mac': '',
        'victim_mac_match': None,
        'victim_on_lan': None,
        'victim_live_ip': '',
        'victim_liveness_note': '',
    }
    vip = str(victim_ip or '').strip()
    want_mac = _norm_mac(victim_mac)
    if not vip:
        out['victim_on_lan'] = False
        out['victim_liveness_note'] = 'no victim IP'
        return out

    ping_ok = None
    try:
        from tools.utils import ipv4_ping_reachable

        ping_ok = bool(ipv4_ping_reachable(vip, timeout_ms=600, attempts=1))
    except Exception:
        ping_ok = None
    out['victim_ping_ok'] = ping_ok

    arp_mac = ''
    try:
        from tools.utils import GLOBAL_MAC, lookup_mac_from_arp_table

        raw = lookup_mac_from_arp_table(vip, iface_ip or None)
        if raw and str(raw) != str(GLOBAL_MAC):
            arp_mac = _norm_mac(raw)
    except Exception:
        arp_mac = ''
    out['victim_arp_mac'] = arp_mac
    out['victim_in_arp'] = bool(arp_mac)
    if want_mac and arp_mac:
        out['victim_mac_match'] = want_mac == arp_mac
    elif want_mac and not arp_mac:
        out['victim_mac_match'] = False

    live_ip = ''
    if want_mac:
        try:
            from tools.utils import lookup_ip_from_arp_table

            live_ip = str(lookup_ip_from_arp_table(want_mac, iface_ip or None) or '').strip()
        except Exception:
            live_ip = ''
    out['victim_live_ip'] = live_ip

    live_ok = None
    live_note = ''
    try:
        from tools.utils import victim_endpoint_live_for_mitm

        live_ok, live_note = victim_endpoint_live_for_mitm(
            vip,
            victim_mac,
            iface_ip or None,
            ping_attempts=1,
            arp_probe_iface=arp_probe_iface or None,
        )
    except Exception as exc:
        live_ok = None
        live_note = str(exc)
    out['victim_liveness_note'] = str(live_note or '')

    if live_ok is True:
        out['victim_on_lan'] = True
    elif live_ip and live_ip != vip:
        # Same console MAC is online at another IP (classic Wi‑Fi vs Ethernet row).
        out['victim_on_lan'] = False
        if not out['victim_liveness_note']:
            out['victim_liveness_note'] = (
                f'{vip} offline — this device is now at {live_ip}. Rescan and use that row.'
            )
    elif live_ok is False:
        out['victim_on_lan'] = False
    elif ping_ok is False and not arp_mac:
        out['victim_on_lan'] = False
    else:
        out['victim_on_lan'] = None
    return out


def collect_host_health(
    *,
    iface_name: str = '',
    iface_ip: str = '',
    iface_guid: str = '',
    gateway_mac: str = '',
    gateway_ip: str = '',
    l2_ready: Optional[bool] = None,
    ip_forwarding_on: Optional[bool] = None,
    admin_ok: Optional[bool] = None,
    victim_in_arp: Optional[bool] = None,
    settings_adapter_live: Optional[bool] = None,
    victim_ping_ok: Optional[bool] = None,
    victim_arp_mac: str = '',
    victim_mac_match: Optional[bool] = None,
    victim_on_lan: Optional[bool] = None,
    victim_live_ip: str = '',
    victim_liveness_note: str = '',
    selected_victim_ip: str = '',
    selected_victim_mac: str = '',
) -> Dict[str, Any]:
    """ZubCut-machine health + selected-victim liveness for Analysis."""
    return {
        'iface_name': str(iface_name or ''),
        'iface_ip': str(iface_ip or ''),
        'iface_guid': str(iface_guid or ''),
        'gateway_mac': str(gateway_mac or ''),
        'gateway_ip': str(gateway_ip or ''),
        'l2_ready': l2_ready,
        'ip_forwarding_on': ip_forwarding_on,
        'admin_ok': admin_ok,
        'victim_in_arp': victim_in_arp,
        'settings_adapter_live': settings_adapter_live,
        'victim_ping_ok': victim_ping_ok,
        'victim_arp_mac': str(victim_arp_mac or ''),
        'victim_mac_match': victim_mac_match,
        'victim_on_lan': victim_on_lan,
        'victim_live_ip': str(victim_live_ip or ''),
        'victim_liveness_note': str(victim_liveness_note or ''),
        'selected_victim_ip': str(selected_victim_ip or ''),
        'selected_victim_mac': str(selected_victim_mac or ''),
    }


def collect_stack_state(
    *,
    mitm_armed: bool = False,
    forwarder_running: bool = False,
    forwarder_hard_drop: bool = False,
    use_windivert: bool = False,
    windivert_running: bool = False,
    windivert_paused: bool = False,
    cut_pct: Optional[int] = None,
    fwd_packets_seen: Optional[int] = None,
    fwd_packets_dropped: Optional[int] = None,
    fwd_packets_forwarded: Optional[int] = None,
    sample_window_ok: Optional[bool] = None,
) -> Dict[str, Any]:
    return {
        'mitm_armed': bool(mitm_armed),
        'forwarder_running': bool(forwarder_running),
        'forwarder_hard_drop': bool(forwarder_hard_drop),
        'use_windivert': bool(use_windivert),
        'windivert_running': bool(windivert_running),
        'windivert_paused': bool(windivert_paused),
        'cut_pct': cut_pct,
        'fwd_packets_seen': fwd_packets_seen,
        'fwd_packets_dropped': fwd_packets_dropped,
        'fwd_packets_forwarded': fwd_packets_forwarded,
        'sample_window_ok': sample_window_ok,
    }


def _fmt_sample(sample: dict, *, label: str) -> List[str]:
    if not sample.get('ok'):
        return [f'[WARN] {label}: capture failed ({sample.get("error") or "unknown"})']
    sec = sample.get('seconds', '?')
    lines = [
        (
            f'[INFO] {label} ({sec}s): total={sample.get("total", 0)} '
            f'ipv4≈{sample.get("ipv4", 0)} arp={sample.get("arp", 0)} '
            f'arp↔victim={sample.get("arp_victim", 0)} ipv6={sample.get("ipv6", 0)}'
        )
    ]
    wan_out = int(sample.get('victim_wan_out_to_us') or 0)
    wan_bypass = int(sample.get('victim_wan_bypass_gw') or 0)
    wan_ret = int(sample.get('wan_return_bypass') or 0)
    lines.append(
        f'[INFO] {label} victim path: wan→us={wan_out} wanBypassGW={wan_bypass} '
        f'wanReturnBypass={wan_ret} lanIPv4={sample.get("victim_lan_ipv4", 0)} '
        f'poisonARP={sample.get("poison_arp_seen", 0)} victim→us={sample.get("victim_to_us", 0)}'
    )
    if wan_bypass or wan_ret:
        lines.append(
            f'[FAIL] {label} victim still has a path around ZubCut '
            f'(bypass={wan_bypass}, returnBypass={wan_ret}) — connection NOT fully severed'
        )
    elif wan_out > 0:
        lines.append(
            f'[PASS] {label} victim WAN attempts are hitting this PC (poison working on victim)'
        )
    return lines


def _fmt_host(host: dict, *, label: str) -> List[str]:
    lines: List[str] = []
    name = host.get('iface_name') or '?'
    ip = host.get('iface_ip') or '?'
    lines.append(f'[INFO] {label} ZubCut host: {name} ({ip})')
    gw_mac = host.get('gateway_mac') or ''
    gw_ip = host.get('gateway_ip') or ''
    if gw_mac or gw_ip:
        lines.append(
            f'[{"PASS" if gw_mac else "FAIL"}] {label} gateway MAC known'
            + (f' ({gw_ip})' if gw_ip else '')
        )
    else:
        lines.append(f'[FAIL] {label} gateway MAC unknown — MITM cannot arm cleanly')
    if host.get('settings_adapter_live') is True:
        lines.append(f'[PASS] {label} Settings adapter live')
    elif host.get('settings_adapter_live') is False:
        lines.append(f'[FAIL] {label} Settings adapter not live')
    if host.get('l2_ready') is True:
        lines.append(f'[PASS] {label} Npcap L2 socket ready')
    elif host.get('l2_ready') is False:
        lines.append(f'[WARN] {label} Npcap L2 socket not ready')
    sel_ip = host.get('selected_victim_ip') or ''
    sel_mac = host.get('selected_victim_mac') or ''
    if sel_ip or sel_mac:
        lines.append(
            f'[INFO] {label} selected victim: {sel_ip or "?"} ({sel_mac or "no MAC"})'
        )
    if host.get('victim_ping_ok') is True:
        lines.append(
            f'[PASS] {label} victim answers ping (LAN view intact — cut must be proven on WAN path)'
        )
    elif host.get('victim_ping_ok') is False:
        lines.append(
            f'[FAIL] {label} victim does not answer ping — may be offline / wrong IP '
            '(this is NOT proof of a successful cut)'
        )
    if host.get('victim_in_arp') is True:
        arp_m = host.get('victim_arp_mac') or ''
        lines.append(
            f'[PASS] {label} victim present in ARP cache'
            + (f' ({arp_m})' if arp_m else '')
        )
    elif host.get('victim_in_arp') is False:
        lines.append(f'[FAIL] {label} victim missing from ARP cache — stale row / not on LAN')
    if host.get('victim_mac_match') is True:
        lines.append(f'[PASS] {label} ARP MAC matches selected row')
    elif host.get('victim_mac_match') is False:
        lines.append(
            f'[FAIL] {label} ARP MAC mismatch — selected '
            f'{sel_mac or "?"} vs live {host.get("victim_arp_mac") or "(none)"}'
        )
    if host.get('victim_on_lan') is True:
        lines.append(f'[PASS] {label} victim appears on LAN now')
    elif host.get('victim_on_lan') is False:
        lines.append(
            f'[FAIL] {label} victim NOT on LAN — do not trust FULL CUT '
            '(rescan; pick the live PS5 IP)'
        )
        note = str(host.get('victim_liveness_note') or '').strip()
        live_at = str(host.get('victim_live_ip') or '').strip()
        if note:
            lines.append(f'[INFO] {label} {note}')
        elif live_at:
            lines.append(
                f'[INFO] {label} same MAC is online at {live_at} — select that row'
            )
    fwd = host.get('ip_forwarding_on')
    if fwd is True:
        lines.append(f'[FAIL] {label} Windows IP forwarding ON')
    elif fwd is False:
        lines.append(f'[PASS] {label} Windows IP forwarding off')
    if host.get('admin_ok') is True:
        lines.append(f'[PASS] {label} running elevated')
    elif host.get('admin_ok') is False:
        lines.append(f'[WARN] {label} not elevated')
    return lines


def _fmt_stack(stack: dict, *, label: str, expect_full_cut: bool) -> List[str]:
    lines: List[str] = []
    if stack.get('use_windivert'):
        lines.append(
            f'[{"PASS" if stack.get("windivert_running") else "FAIL"}] '
            f'{label} WinDivert gate running'
        )
        lines.append(
            f'[{"PASS" if stack.get("windivert_paused") else "WARN"}] '
            f'{label} WinDivert pause/block'
        )
        return lines
    lines.append(
        f'[{"PASS" if stack.get("mitm_armed") else "FAIL"}] {label} ARP MITM armed'
    )
    lines.append(
        f'[{"PASS" if stack.get("forwarder_running") else "WARN"}] '
        f'{label} Npcap forwarder running'
    )
    if expect_full_cut:
        lines.append(
            f'[{"PASS" if stack.get("forwarder_hard_drop") else "WARN"}] '
            f'{label} forwarder hard-drop'
        )
    seen = stack.get('fwd_packets_seen')
    dropped = stack.get('fwd_packets_dropped')
    forwarded = stack.get('fwd_packets_forwarded')
    if seen is not None or dropped is not None:
        lines.append(
            f'[INFO] {label} forwarder stats: seen={seen if seen is not None else "?"} '
            f'dropped={dropped if dropped is not None else "?"} '
            f'forwarded={forwarded if forwarded is not None else "?"}'
        )
        if expect_full_cut and dropped is not None:
            lines.append(
                f'[{"PASS" if int(dropped or 0) > 0 else "WARN"}] '
                f'{label} forwarder actually dropped packets'
            )
    if stack.get('sample_window_ok') is False:
        lines.append(
            f'[FAIL] {label} cut already OFF when sample started — increase Dupe/hold time '
            '(Analysis needs ≥8000 ms)'
        )
    elif stack.get('sample_window_ok') is True:
        lines.append(f'[PASS] {label} sample window caught cut while still armed')
    if stack.get('cut_pct') is not None:
        lines.append(f'[INFO] {label} Percent Cut target: {int(stack["cut_pct"])}% cut')
    return lines


def _phase_banner(phase: str, passed: bool) -> List[str]:
    mark = 'PASS' if passed else 'FAIL'
    bar = '=' * 64
    return [
        bar,
        f'  {phase}  >>>  {mark}',
        bar,
        f'  >>> THIS SECTION: {"PASSED" if passed else "FAILED"} <<<',
        bar,
    ]


def _full_cut_checklist(
    *,
    host: dict,
    stack: dict,
    sample: dict,
    before: Optional[PhaseSample],
    expect_full_cut: bool,
) -> List[str]:
    """Explicit PASS/FAIL deep-dive lines for full cut vs partial."""
    if not expect_full_cut:
        return [
            'Full-cut deep dive: skipped (this flow is Percent Cut / Lag allow — not a red-chain offline cut).',
        ]
    b_host = (before.host if before else {}) or {}
    victim_on_lan = host.get('victim_on_lan')
    if victim_on_lan is None:
        victim_on_lan = b_host.get('victim_on_lan')
    use_wd = bool(stack.get('use_windivert'))
    checks: List[Tuple[str, bool]] = [
        ('Victim on LAN (ping/ARP/MAC)', victim_on_lan is True),
        ('Settings adapter live', host.get('settings_adapter_live') is not False),
        ('Gateway MAC known', bool(host.get('gateway_mac') or b_host.get('gateway_mac'))),
        ('Windows IP forwarding OFF', host.get('ip_forwarding_on') is not True),
    ]
    if stack.get('sample_window_ok') is False:
        checks.append(('Sample caught cut while still ON', False))
    else:
        checks.append(('Sample caught cut while still ON', stack.get('sample_window_ok') is not False))
    if use_wd:
        checks.extend(
            [
                ('WinDivert gate running', bool(stack.get('windivert_running'))),
                ('WinDivert pause/block armed', bool(stack.get('windivert_paused'))),
            ]
        )
    else:
        checks.extend(
            [
                ('ARP MITM armed', bool(stack.get('mitm_armed'))),
                ('Npcap forwarder running', bool(stack.get('forwarder_running'))),
                ('Forwarder hard-drop 0% (red chain)', bool(stack.get('forwarder_hard_drop'))),
            ]
        )
    ipv6 = int((sample or {}).get('ipv6') or 0)
    checks.append(('No strong IPv6 bypass signal', ipv6 <= 8))
    bypass = _victim_wan_bypass(sample)
    severed = _victim_severance_evidence(stack, sample)
    checks.append(
        (
            'Victim still visible on LAN (not ZubCut blocking its own view)',
            victim_on_lan is True,
        )
    )
    checks.append(('No victim WAN bypass around MITM', not bypass))
    checks.append(
        (
            'Victim WAN path severed (WAN→us dropped / forwarder drops)',
            severed and not bypass,
        )
    )
    lines = ['--- FULL CUT DEEP DIVE (victim path) ---']
    for label, ok in checks:
        lines.append(f'[{"PASS" if ok else "FAIL"}] {label}')
    all_ok = all(ok for _, ok in checks)
    lines.append(
        '[RESULT] Deep dive: victim connection FULLY SEVERED'
        if all_ok
        else '[RESULT] Deep dive: victim connection NOT proven severed (partial / bypass / local-only view)'
    )
    return lines


def _victim_wan_bypass(sample: dict) -> bool:
    """True if the victim still exchanges WAN traffic via the real gateway (around us)."""
    return (
        int((sample or {}).get('victim_wan_bypass_gw') or 0) > 0
        or int((sample or {}).get('wan_return_bypass') or 0) > 0
    )


def _victim_severance_evidence(stack: dict, sample: dict) -> bool:
    """
    Proof the *victim's* WAN path hit our choke and was cut.

    Deliberately ignores ZubCut-local-only signals (generic ipv4, poison ARP alone,
    "we can't ping them") — those can look like a cut while the PS5 is still online.
    """
    if int((sample or {}).get('victim_wan_out_to_us') or 0) > 0:
        return True
    # Forwarder drop counters mean victim frames reached the MITM choke and were killed.
    if int(stack.get('fwd_packets_dropped') or 0) > 0:
        return True
    return False


def _cut_evidence(stack: dict, sample: dict) -> bool:
    """Backward-compatible alias — prefer victim-severance evidence."""
    return _victim_severance_evidence(stack, sample)


def _eval_before(ps: Optional[PhaseSample]) -> PhaseResult:
    if ps is None:
        return PhaseResult(PHASE_BEFORE, False, ['BEFORE phase missing'])
    host = ps.host or {}
    fails: List[str] = []
    notes: List[str] = []
    if host.get('settings_adapter_live') is False:
        fails.append('Settings adapter not live on ZubCut PC')
    if not host.get('gateway_mac'):
        fails.append('gateway MAC unknown — MITM cannot arm cleanly')
    if host.get('l2_ready') is False:
        fails.append('Npcap L2 socket not ready')
    if host.get('victim_on_lan') is False:
        note = str(host.get('victim_liveness_note') or '').strip()
        live_at = str(host.get('victim_live_ip') or '').strip()
        fails.append(
            note
            or (
                'selected victim not on LAN'
                + (f' (device now at {live_at})' if live_at else '')
            )
        )
    elif host.get('victim_on_lan') is True:
        notes.append('victim confirmed on LAN (ping/ARP)')
    else:
        fails.append('victim LAN presence not confirmed before cut')
    if host.get('victim_mac_match') is False:
        fails.append('ARP MAC does not match selected row (stale/ghost identity)')
    if not (ps.sample or {}).get('ok'):
        notes.append('BEFORE traffic sample failed (host checks still apply)')
    return PhaseResult(PHASE_BEFORE, not fails, fails, notes)


def _eval_during_full_cut(
    ps: Optional[PhaseSample],
    *,
    before: Optional[PhaseSample],
    expect_full_cut: bool,
    cut_pct: Optional[int],
) -> Tuple[PhaseResult, str]:
    """
    Deep full-cut check for DURING.

    Returns (phase_result, cut_verdict) where cut_verdict is
    FULL CUT / PARTIAL / NOT CUT / INCONCLUSIVE.
    """
    if ps is None:
        return PhaseResult(PHASE_DURING, False, ['DURING phase missing']), 'INCONCLUSIVE'

    host = ps.host or {}
    stack = ps.stack or {}
    sample = ps.sample or {}
    b_host = (before.host if before else {}) or {}
    b_sample = (before.sample if before else {}) or {}
    fails: List[str] = []
    notes: List[str] = []
    verdict = 'INCONCLUSIVE'

    victim_on_lan = host.get('victim_on_lan')
    if victim_on_lan is None:
        victim_on_lan = b_host.get('victim_on_lan')

    if host.get('settings_adapter_live') is False:
        fails.append('Settings adapter not live during cut')
    if host.get('ip_forwarding_on') is True and expect_full_cut and not stack.get('use_windivert'):
        fails.append('Windows IP forwarding ON during cut (kernel can relay = partial)')

    if victim_on_lan is False:
        note = str(
            host.get('victim_liveness_note') or b_host.get('victim_liveness_note') or ''
        ).strip()
        live_at = str(host.get('victim_live_ip') or b_host.get('victim_live_ip') or '').strip()
        fails.append(
            note
            or (
                'victim not on LAN during cut'
                + (f' (same device now at {live_at})' if live_at else '')
            )
        )
        verdict = 'NOT CUT'
        return PhaseResult(PHASE_DURING, False, fails, notes), verdict

    if victim_on_lan is not True:
        fails.append('victim on-LAN not confirmed during cut (ping/ARP)')

    # Missed sample window (Dupe too short / OFF before DURING settled).
    if expect_full_cut and stack.get('sample_window_ok') is False:
        fails.append(
            'DURING sample started after the cut already turned OFF — increase hold/Dupe '
            'duration to at least 8000 ms (5s is often too short once arm + settle + sniff run)'
        )
        verdict = 'INCONCLUSIVE'
        return PhaseResult(PHASE_DURING, False, fails, notes), verdict

    use_wd = bool(stack.get('use_windivert'))
    bypass = _victim_wan_bypass(sample)
    severed = _victim_severance_evidence(stack, sample)
    # Victim must remain visible on LAN during a real MITM cut. Losing ping/ARP here
    # usually means a ghost IP or ZubCut lost its own view — NOT proof the PS5 is offline.
    if expect_full_cut and victim_on_lan is True:
        notes.append(
            'victim still visible on LAN during cut (ZubCut is not just blocking its own view)'
        )
    elif expect_full_cut and host.get('victim_ping_ok') is False and host.get('victim_on_lan') is True:
        notes.append('victim ARP-live but ICMP silent (normal for some consoles during cut)')

    if use_wd:
        if not stack.get('windivert_running'):
            fails.append('WinDivert gate not running')
            verdict = 'NOT CUT'
        elif expect_full_cut and not stack.get('windivert_paused'):
            fails.append('WinDivert running but not paused/blocked (not a full cut)')
            verdict = 'PARTIAL'
        elif expect_full_cut:
            if bypass:
                fails.append(
                    'Victim WAN traffic still bypasses WinDivert path — connection NOT severed'
                )
                verdict = 'PARTIAL'
            elif not severed:
                fails.append(
                    'WinDivert pause armed but no victim-WAN severance evidence — '
                    'keep the console online/active (game traffic) and use ≥8000 ms'
                )
                verdict = 'INCONCLUSIVE'
            else:
                notes.append('WinDivert pause armed + victim WAN path evidence')
                verdict = 'FULL CUT'
        else:
            notes.append('Percent Cut / shaping path (not full offline)')
            verdict = 'PARTIAL'
            if expect_full_cut is False:
                # Percent Cut: DURING "pass" means armed as intended, not full offline.
                return PhaseResult(PHASE_DURING, not fails, fails, notes), verdict
    else:
        if not stack.get('mitm_armed'):
            fails.append('ARP MITM not armed during cut')
            verdict = 'NOT CUT'
        elif not expect_full_cut:
            if not stack.get('forwarder_running') and not stack.get('mitm_armed'):
                fails.append('Percent Cut stack not armed')
                verdict = 'NOT CUT'
            else:
                notes.append(
                    f'Percent Cut / Lag armed ({int(cut_pct) if cut_pct is not None else "?"}% cut) '
                    '— not a full offline / red-chain cut'
                )
                verdict = 'PARTIAL'
        else:
            # Deep full-cut checklist — prove the *victim* WAN path is severed.
            if not stack.get('forwarder_running'):
                fails.append(
                    'Npcap forwarder not running — ARP-only is PARTIAL '
                    '(kick/lag without red chain)'
                )
                verdict = 'PARTIAL'
            if stack.get('forwarder_running') and not stack.get('forwarder_hard_drop'):
                fails.append('forwarder not in hard-drop 0% mode — PARTIAL cut')
                verdict = 'PARTIAL'
            if host.get('ip_forwarding_on') is True:
                fails.append('IP forwarding ON — traffic can leak past MITM')
                verdict = 'PARTIAL'
            if not host.get('gateway_mac'):
                fails.append('gateway MAC unknown during cut')
                verdict = 'PARTIAL' if verdict != 'NOT CUT' else verdict
            if sample.get('ok') and int(sample.get('ipv6') or 0) > 8:
                fails.append('notable IPv6 during cut — possible bypass of IPv4 MITM')
                verdict = 'PARTIAL'

            if bypass:
                fails.append(
                    'Victim still exchanges WAN traffic via the real gateway MAC '
                    f'(bypass={int(sample.get("victim_wan_bypass_gw") or 0)}, '
                    f'returnBypass={int(sample.get("wan_return_bypass") or 0)}) — '
                    'connection NOT severed (poison incomplete / wrong NIC)'
                )
                verdict = 'PARTIAL'

            # Attraction gap: BEFORE had traffic, DURING has no victim-WAN severance.
            if (
                b_sample.get('ok')
                and sample.get('ok')
                and (
                    int(b_sample.get('ipv4') or 0) > 0
                    or int(b_sample.get('victim_wan_out_to_us') or 0) > 0
                    or int(b_sample.get('victim_wan_bypass_gw') or 0) > 0
                )
                and not severed
                and not bypass
            ):
                fails.append(
                    'BEFORE saw victim traffic but DURING has no victim-WAN severance evidence '
                    '(need wan→us and/or forwarder drops) — traffic not pulled to this PC, '
                    'or console went idle'
                )
                if verdict != 'PARTIAL':
                    verdict = 'INCONCLUSIVE'
            elif not severed and not bypass and stack.get('mitm_armed') and stack.get(
                'forwarder_running'
            ):
                fails.append(
                    'Cut stack armed but victim WAN path not proven severed '
                    '(need victim wan→us packets and/or forwarder drops; poison ARP alone '
                    'or losing ping to the PS5 does NOT count). Keep the console in a game '
                    'with network activity and use ≥8000 ms for Analysis'
                )
                verdict = 'INCONCLUSIVE'

            fwd_leaks = int(stack.get('fwd_packets_forwarded') or 0)
            fwd_drops = int(stack.get('fwd_packets_dropped') or 0)
            if (
                stack.get('forwarder_hard_drop')
                and fwd_leaks > 0
                and fwd_drops == 0
                and fwd_leaks >= 3
            ):
                fails.append(
                    f'forwarder forwarded {fwd_leaks} packets with 0 drops while hard-drop '
                    'claimed — victim traffic may still be leaking'
                )
                verdict = 'PARTIAL'

            if (
                not fails
                and stack.get('mitm_armed')
                and stack.get('forwarder_running')
                and stack.get('forwarder_hard_drop')
                and severed
                and not bypass
                and victim_on_lan is True
            ):
                verdict = 'FULL CUT'
                notes.append(
                    'Victim WAN path severed: still on LAN, MITM+hard-drop armed, '
                    'WAN attempts hitting this PC / forwarder drops, no gateway bypass'
                )
            elif not fails and verdict == 'INCONCLUSIVE':
                fails.append('victim-path full-cut checklist incomplete')
            elif fails and verdict == 'INCONCLUSIVE':
                pass  # keep INCONCLUSIVE (not proven) rather than forcing PARTIAL

    # Any DURING failure means the cut did not fully work.
    passed = (verdict == 'FULL CUT') if expect_full_cut else (verdict in ('PARTIAL', 'FULL CUT') and not any(
        'not armed' in f.lower() or 'not running' in f.lower() for f in fails
    ) and victim_on_lan is True)
    if expect_full_cut and verdict != 'FULL CUT':
        passed = False
        if not fails:
            fails.append(f'cut verdict is {verdict}, not FULL CUT')
    return PhaseResult(PHASE_DURING, passed, fails, notes), verdict


def _eval_after(ps: Optional[PhaseSample]) -> PhaseResult:
    if ps is None:
        return PhaseResult(PHASE_AFTER, False, ['AFTER phase missing'])
    stack = ps.stack or {}
    host = ps.host or {}
    fails: List[str] = []
    notes: List[str] = []
    if stack.get('use_windivert'):
        if stack.get('windivert_paused'):
            fails.append('WinDivert still paused after OFF — victim may stay cut')
        else:
            notes.append('WinDivert not paused after OFF')
    else:
        if stack.get('mitm_armed'):
            fails.append('ARP MITM still armed after OFF — victim may stay cut')
        else:
            notes.append('ARP MITM cleared')
        if stack.get('forwarder_running'):
            fails.append('Npcap forwarder still running after OFF')
        else:
            notes.append('forwarder cleared')
    # Hard-drop flags left set after OFF is a restore leak (even if forwarder thread stopped).
    if stack.get('forwarder_hard_drop'):
        fails.append('forwarder still in hard-drop mode after OFF')
    if host.get('victim_on_lan') is False:
        notes.append(
            'victim not on LAN after OFF — may still be waking; not scored as cut failure alone'
        )
    return PhaseResult(PHASE_AFTER, not fails, fails, notes)


def score_phases(
    *,
    flow: str,
    victim_ip: str,
    victim_mac: str,
    expect_full_cut: bool,
    before: Optional[PhaseSample] = None,
    during: Optional[PhaseSample] = None,
    after: Optional[PhaseSample] = None,
    cut_pct: Optional[int] = None,
) -> CutAnalysisReport:
    """Build one BEFORE/DURING/AFTER report with PASS/FAIL headers + overall SUCCESS/FAIL."""
    flow = str(flow or 'Cut').strip() or 'Cut'
    victim_ip = str(victim_ip or '').strip()
    victim_mac = str(victim_mac or '').strip()

    before_r = _eval_before(before)
    during_r, verdict = _eval_during_full_cut(
        during, before=before, expect_full_cut=expect_full_cut, cut_pct=cut_pct
    )
    after_r = _eval_after(after)

    phase_results = {
        PHASE_BEFORE: before_r,
        PHASE_DURING: during_r,
        PHASE_AFTER: after_r,
    }

    # Overall: SUCCESS only when every phase passes AND (for full-cut flows) verdict is FULL CUT.
    any_phase_fail = not (before_r.passed and during_r.passed and after_r.passed)
    if expect_full_cut:
        overall = 'SUCCESS' if (not any_phase_fail and verdict == 'FULL CUT') else 'FAIL'
    else:
        # Percent Cut: success = armed + restore clean (not a red-chain full cut).
        overall = 'SUCCESS' if not any_phase_fail else 'FAIL'

    if any_phase_fail and verdict == 'FULL CUT':
        # Phase failure always means the cut run failed, even if DURING looked armed.
        verdict = 'PARTIAL'

    reasons: List[str] = []
    for pr in (before_r, during_r, after_r):
        for f in pr.failures:
            reasons.append(f'{pr.phase}: {f}')
        for n in pr.notes:
            reasons.append(f'{pr.phase}: {n}')

    lines: List[str] = []
    lines.append('======== ZubCut Cut Analysis ========')
    lines.append('')
    lines.append('#' * 64)
    if overall == 'SUCCESS':
        lines.append('  OVERALL RESULT:  SUCCESS')
        lines.append(
            '  Victim WAN path severed (not just ZubCut blocking its own view of the PS5).'
            if expect_full_cut
            else '  Percent Cut path armed and restored cleanly.'
        )
    else:
        lines.append('  OVERALL RESULT:  FAIL')
        lines.append(
            '  Victim connection NOT proven severed — see FAIL sections below.'
            if expect_full_cut
            else '  The cut DID NOT fully work — see FAIL sections below.'
        )
    lines.append('#' * 64)
    lines.append('')
    lines.append(f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}Z')
    lines.append(f'Flow: {flow}')
    lines.append(f'Victim: {victim_ip or "?"} ({victim_mac or "no MAC"})')
    lines.append(f'Cut verdict: {verdict}')
    lines.append(
        f'Phase results: BEFORE={"PASS" if before_r.passed else "FAIL"} | '
        f'DURING={"PASS" if during_r.passed else "FAIL"} | '
        f'AFTER={"PASS" if after_r.passed else "FAIL"}'
    )
    lines.append('')

    phases: Dict[str, PhaseSample] = {}
    for ps, pr in (
        (before, before_r),
        (during, during_r),
        (after, after_r),
    ):
        if ps is None and pr.phase:
            lines.extend(_phase_banner(pr.phase, False))
            lines.append(f'[FAIL] {pr.phase} data missing from this run')
            lines.append('')
            continue
        if ps is None:
            continue
        phases[ps.phase] = ps
        lines.extend(_phase_banner(ps.phase, pr.passed))
        lines.append(
            f'[RESULT] {ps.phase}: {"PASS" if pr.passed else "FAIL"}'
        )
        if pr.failures:
            for f in pr.failures:
                lines.append(f'[FAIL] {ps.phase}: {f}')
        if pr.notes:
            for n in pr.notes:
                lines.append(f'[INFO] {ps.phase}: {n}')
        if ps.note:
            lines.append(f'[INFO] {ps.note}')
        lines.extend(_fmt_host(ps.host or {}, label=ps.phase))
        lines.extend(_fmt_sample(ps.sample or {}, label=f'{ps.phase} victim traffic'))
        if ps.phase in (PHASE_DURING, PHASE_AFTER):
            lines.extend(
                _fmt_stack(
                    ps.stack or {},
                    label=ps.phase,
                    expect_full_cut=expect_full_cut if ps.phase == PHASE_DURING else False,
                )
            )
        if ps.phase == PHASE_DURING:
            lines.extend(
                _full_cut_checklist(
                    host=ps.host or {},
                    stack=ps.stack or {},
                    sample=ps.sample or {},
                    before=before,
                    expect_full_cut=expect_full_cut,
                )
            )
        lines.append('')

    lines.append('>>> SUMMARY')
    lines.append(f'  OVERALL: {overall}')
    lines.append(f'  CUT:     {verdict}')
    if overall == 'FAIL':
        lines.append(
            '  Meaning: victim WAN path not severed (bypass, partial, or only local-view signals).'
            if expect_full_cut
            else '  Meaning: cut did not work (or was only partial / not proven).'
        )
    else:
        lines.append(
            '  Meaning: victim still on LAN + WAN path through ZubCut hard-dropped + no gateway bypass.'
            if expect_full_cut
            else '  Meaning: intended % cut path OK.'
        )
    for r in reasons:
        lines.append(f'  - {r}')
    lines.append('')
    lines.append('Full-cut requirements (DURING) — victim path, not ZubCut-local view:')
    lines.append('  sample window still ON (Dupe/hold ≥8000 ms recommended for Analysis)')
    lines.append('  victim STILL visible on LAN (ping/ARP) — proves we are not just hiding the PS5 from this PC')
    lines.append('  ARP MITM armed + Npcap forwarder hard-drop 0% (red chain)')
    lines.append('  Windows IP forwarding OFF')
    lines.append('  victim WAN attempts hit this PC (wan→us) and/or forwarder drops > 0')
    lines.append('  NO victim WAN bypass via real gateway MAC (out or return)')
    lines.append('  no strong IPv6 bypass signal')
    lines.append('  AFTER: MITM/forwarder fully cleared on OFF')
    lines.append('  NOTE: poison ARP alone or "cannot ping PS5" is NOT proof the console lost internet')
    lines.append('=====================================')

    return CutAnalysisReport(
        flow=flow,
        verdict=verdict,
        overall=overall,
        victim_ip=victim_ip,
        victim_mac=victim_mac,
        lines=lines,
        phases=phases,
        phase_results=phase_results,
    )


def analyze_victim_cut(
    *,
    flow: str,
    victim_ip: str,
    victim_mac: str,
    gateway_mac: str = '',
    iface_guid: str = '',
    iface_name: str = '',
    seconds: float = 2.0,
    expect_full_cut: bool = True,
    cut_pct: Optional[int] = None,
    mitm_armed: bool = False,
    forwarder_running: bool = False,
    forwarder_hard_drop: bool = False,
    ip_forwarding_on: Optional[bool] = None,
    use_windivert: bool = False,
    windivert_paused: bool = False,
    windivert_running: bool = False,
    local_mac: str = '',
    before: Optional[PhaseSample] = None,
    after: Optional[PhaseSample] = None,
    host: Optional[dict] = None,
) -> CutAnalysisReport:
    """
    Compatibility wrapper: take a DURING sample (+ optional before/after) and score.
    """
    _ = _norm_mac(local_mac)
    sample = _sniff_cut_sample(iface_guid, victim_ip, seconds=seconds)
    host_d = dict(host or {})
    if gateway_mac and not host_d.get('gateway_mac'):
        host_d['gateway_mac'] = gateway_mac
    if iface_name and not host_d.get('iface_name'):
        host_d['iface_name'] = iface_name
    if iface_guid and not host_d.get('iface_guid'):
        host_d['iface_guid'] = iface_guid
    if ip_forwarding_on is not None and host_d.get('ip_forwarding_on') is None:
        host_d['ip_forwarding_on'] = ip_forwarding_on
    during = PhaseSample(
        phase=PHASE_DURING,
        sample=sample,
        host=host_d,
        stack=collect_stack_state(
            mitm_armed=mitm_armed,
            forwarder_running=forwarder_running,
            forwarder_hard_drop=forwarder_hard_drop,
            use_windivert=use_windivert,
            windivert_running=windivert_running,
            windivert_paused=windivert_paused,
            cut_pct=cut_pct,
        ),
    )
    return score_phases(
        flow=flow,
        victim_ip=victim_ip,
        victim_mac=victim_mac,
        expect_full_cut=expect_full_cut,
        before=before,
        during=during,
        after=after,
        cut_pct=cut_pct,
    )


def _open_analysis_report(path: Path) -> None:
    """Open the saved Analysis .txt in Notepad (same as Quick check / Capture stack)."""
    import os
    import subprocess
    import sys

    try:
        if sys.platform.startswith('win'):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
    except Exception:
        pass
    try:
        subprocess.Popen(
            ['notepad.exe', str(path)],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def missing_during_phase_sample(
    *,
    host: Optional[Dict[str, Any]] = None,
    stack: Optional[Dict[str, Any]] = None,
    note: str = '',
) -> PhaseSample:
    """Placeholder DURING when MITM never armed (stale IP) so a report can still save."""
    return PhaseSample(
        phase=PHASE_DURING,
        sample={
            'ok': False,
            'error': 'DURING sample missing — cut may not have armed on this IP',
            'ipv4': 0,
            'ipv6': 0,
            'arp': 0,
            'arp_victim': 0,
            'poison_arp_seen': 0,
            'victim_to_us': 0,
            'victim_wan_out_to_us': 0,
            'victim_wan_bypass_gw': 0,
            'wan_return_bypass': 0,
            'victim_lan_ipv4': 0,
            'total': 0,
            'seconds': 0,
        },
        host=dict(host or {}),
        stack=dict(stack or {}),
        note=note
        or 'DURING missing — flow ended without an armed cut sample (stale/offline IP?)',
    )


def save_cut_analysis_report(
    report: CutAnalysisReport, *, open_report: bool = False
) -> Optional[Path]:
    """
    Write report under ``Desktop\\ZubCut Diagnostics`` (same folder as Quick check).

    Uses ``diag_paths.ensure_zubcut_diagnostics_dir`` so OneDrive Desktop redirect
    matches elevated PS1 diagnostics. Optionally opens Notepad.
    """
    try:
        from tools.diag_paths import DIAGNOSTICS_FOLDER_NAME, ensure_zubcut_diagnostics_dir
        from tools.diag_privacy import redact_ipv4s_in_text
    except Exception:
        return None
    try:
        folder = ensure_zubcut_diagnostics_dir().resolve()
        # Guard: never write outside Desktop\ZubCut Diagnostics.
        if folder.name != DIAGNOSTICS_FOLDER_NAME:
            folder = folder / DIAGNOSTICS_FOLDER_NAME
            folder.mkdir(parents=True, exist_ok=True)
            folder = folder.resolve()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        flow_slug = ''.join(ch if ch.isalnum() else '-' for ch in report.flow).strip('-') or 'cut'
        # Avoid characters that break Windows paths in flow labels like "Kill (during)".
        flow_slug = flow_slug.replace('(', '').replace(')', '').strip('-') or 'cut'
        path = folder / f'ZubCut-Analysis-{flow_slug}-{stamp}.txt'
        lines = list(report.lines)
        # Stamp the real save location at the top (OneDrive Desktop etc.).
        loc_line = f'Saved to: {path}'
        if lines and lines[0].startswith('========'):
            lines.insert(1, loc_line)
        else:
            lines.insert(0, loc_line)
        body = '\n'.join(lines) + '\n'
        try:
            body = redact_ipv4s_in_text(body)
        except Exception:
            pass
        path.write_text(body, encoding='utf-8', newline='\r\n')
        report.report_path = str(path)
        report.lines = lines
        if open_report:
            _open_analysis_report(path)
        return path
    except Exception:
        return None
