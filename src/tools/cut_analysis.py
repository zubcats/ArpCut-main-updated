"""Deep cut Analysis — before / during / after victim + ZubCut-host checks.

Phases (never on the instant-cut hot path):
  BEFORE  — baseline while Analysis is ON (rolling) or frozen at flow start
  DURING  — after Kill/Lag/Dupe/% Cut arm
  AFTER   — after flow OFF / restore

Scores FULL CUT / PARTIAL / NOT CUT / INCONCLUSIVE and writes a privacy-masked
report under Desktop\\ZubCut Diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


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
class CutAnalysisReport:
    flow: str
    verdict: str
    victim_ip: str
    victim_mac: str
    lines: List[str] = field(default_factory=list)
    report_path: Optional[str] = None
    phases: Dict[str, PhaseSample] = field(default_factory=dict)

    @property
    def summary_line(self) -> str:
        return (
            f'Analysis [{self.flow}]: {self.verdict} — '
            f'{self.victim_ip or "?"} ({self.victim_mac or "no MAC"})'
        )


def _norm_mac(mac: str) -> str:
    return str(mac or '').strip().lower().replace('-', ':')


def _sniff_cut_sample(
    iface_guid: str,
    victim_ip: str,
    *,
    seconds: float = 1.5,
) -> dict[str, Any]:
    """Capture a short sample; return packet class counts (best-effort)."""
    out: dict[str, Any] = {
        'ok': False,
        'error': '',
        'ipv4': 0,
        'ipv6': 0,
        'arp': 0,
        'arp_victim': 0,
        'total': 0,
        'seconds': float(seconds),
    }
    victim_ip = str(victim_ip or '').strip()
    iface_guid = str(iface_guid or '').strip()
    if not victim_ip or not iface_guid:
        out['error'] = 'missing iface or victim IP'
        return out
    try:
        from scapy.all import ARP, IPv6, sniff  # type: ignore
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
                if vip in (psrc, pdst):
                    out['arp_victim'] += 1
                continue
            if pkt.haslayer(IPv6):
                out['ipv6'] += 1
                continue
            out['ipv4'] += 1
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
) -> Dict[str, Any]:
    return {
        'mitm_armed': bool(mitm_armed),
        'forwarder_running': bool(forwarder_running),
        'forwarder_hard_drop': bool(forwarder_hard_drop),
        'use_windivert': bool(use_windivert),
        'windivert_running': bool(windivert_running),
        'windivert_paused': bool(windivert_paused),
        'cut_pct': cut_pct,
    }


def _fmt_sample(sample: dict, *, label: str) -> str:
    if not sample.get('ok'):
        return f'[WARN] {label}: capture failed ({sample.get("error") or "unknown"})'
    sec = sample.get('seconds', '?')
    return (
        f'[INFO] {label} ({sec}s): total={sample.get("total", 0)} '
        f'ipv4≈{sample.get("ipv4", 0)} arp={sample.get("arp", 0)} '
        f'arp↔victim={sample.get("arp_victim", 0)} ipv6={sample.get("ipv6", 0)}'
    )


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
        lines.append(f'[PASS] {label} victim answers ping')
    elif host.get('victim_ping_ok') is False:
        lines.append(f'[FAIL] {label} victim does not answer ping — may be offline / wrong IP')
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
    if stack.get('cut_pct') is not None:
        lines.append(f'[INFO] {label} Percent Cut target: {int(stack["cut_pct"])}% cut')
    return lines


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
    """Build the full before/during/after report and verdict."""
    flow = str(flow or 'Cut').strip() or 'Cut'
    victim_ip = str(victim_ip or '').strip()
    victim_mac = str(victim_mac or '').strip()
    lines: List[str] = []
    lines.append('======== ZubCut Cut Analysis ========')
    lines.append(f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}Z')
    lines.append(f'Flow: {flow}')
    lines.append(f'Victim: {victim_ip or "?"} ({victim_mac or "no MAC"})')
    present = []
    if before is not None:
        present.append('BEFORE')
    if during is not None:
        present.append('DURING')
    if after is not None:
        present.append('AFTER')
    lines.append(
        'Phases in this report: '
        + (' → '.join(present) if present else '(none)')
        + ' (single end-of-run file)'
    )
    lines.append('')

    phases: Dict[str, PhaseSample] = {}
    for ps in (before, during, after):
        if ps is None:
            continue
        phases[ps.phase] = ps
        lines.append(f'--- {ps.phase} ---')
        if ps.note:
            lines.append(f'[INFO] {ps.note}')
        lines.extend(_fmt_host(ps.host or {}, label=ps.phase))
        lines.append(_fmt_sample(ps.sample or {}, label=f'{ps.phase} victim traffic'))
        if ps.phase in (PHASE_DURING, PHASE_AFTER):
            lines.extend(
                _fmt_stack(
                    ps.stack or {},
                    label=ps.phase,
                    expect_full_cut=expect_full_cut if ps.phase == PHASE_DURING else False,
                )
            )
        lines.append('')

    reasons: List[str] = []
    verdict = 'INCONCLUSIVE'
    d_stack = (during.stack if during else {}) or {}
    d_sample = (during.sample if during else {}) or {}
    b_sample = (before.sample if before else {}) or {}
    a_sample = (after.sample if after else {}) or {}
    a_stack = (after.stack if after else {}) or {}
    d_host = (during.host if during else {}) or {}

    use_wd = bool(d_stack.get('use_windivert'))
    b_host = (before.host if before else {}) or {}
    # Prefer DURING liveness; fall back to BEFORE baseline.
    victim_on_lan = d_host.get('victim_on_lan')
    if victim_on_lan is None:
        victim_on_lan = b_host.get('victim_on_lan')

    # Host failures can cap the verdict.
    if d_host.get('settings_adapter_live') is False:
        reasons.append('Settings adapter not live on ZubCut PC')
    if d_host.get('gateway_mac') in ('', None) and not use_wd:
        reasons.append('gateway MAC unknown on ZubCut PC')
    if d_host.get('ip_forwarding_on') is True and expect_full_cut and not use_wd:
        reasons.append('IP forwarding ON during cut')

    # Stale IP / offline console: stack may still arm, but that is not a real cut.
    if victim_on_lan is False:
        note = str(
            d_host.get('victim_liveness_note')
            or b_host.get('victim_liveness_note')
            or ''
        ).strip()
        live_at = str(
            d_host.get('victim_live_ip') or b_host.get('victim_live_ip') or ''
        ).strip()
        reasons.append(
            note
            or (
                f'victim not on LAN'
                + (f' (same device now at {live_at})' if live_at else '')
                + ' — stale row / offline IP'
            )
        )

    if victim_on_lan is False:
        # Armed MITM against a ghost must never read as FULL CUT.
        verdict = 'NOT CUT'
        if d_stack.get('mitm_armed') or d_stack.get('windivert_running'):
            reasons.append(
                'ZubCut stack armed, but selected IP/MAC is not live on the LAN'
            )
    elif during is None:
        verdict = 'INCONCLUSIVE'
        reasons.append('no DURING sample (cut may have ended too fast)')
    elif use_wd:
        if not d_stack.get('windivert_running'):
            verdict = 'NOT CUT'
            reasons.append('WinDivert gate not running')
        elif expect_full_cut and not d_stack.get('windivert_paused'):
            verdict = 'PARTIAL'
            reasons.append('WinDivert running but not paused/blocked')
        else:
            verdict = 'FULL CUT' if expect_full_cut else 'PARTIAL'
            reasons.append(
                'WinDivert pause armed'
                if expect_full_cut
                else 'Percent Cut / shaping path (not full offline)'
            )
    else:
        if not d_stack.get('mitm_armed'):
            verdict = 'NOT CUT'
            reasons.append('ARP MITM not armed during cut')
        elif expect_full_cut:
            if not d_stack.get('forwarder_running'):
                verdict = 'PARTIAL'
                reasons.append('Npcap forwarder not running (ARP-only — often no red chain)')
            elif not d_stack.get('forwarder_hard_drop'):
                verdict = 'PARTIAL'
                reasons.append('forwarder not in hard-drop mode')
            elif d_host.get('ip_forwarding_on') is True:
                verdict = 'PARTIAL'
                reasons.append('kernel IP forwarding still ON')
            else:
                verdict = 'FULL CUT'
                reasons.append('MITM armed + hard-drop forwarder during cut')
            if d_sample.get('ok') and int(d_sample.get('ipv6') or 0) > 8:
                verdict = 'PARTIAL'
                reasons.append('notable IPv6 during cut (possible bypass)')
            # Before→during traffic attraction signal
            if (
                b_sample.get('ok')
                and d_sample.get('ok')
                and int(b_sample.get('ipv4') or 0) > 0
                and int(d_sample.get('ipv4') or 0) == 0
                and int(d_sample.get('arp_victim') or 0) == 0
            ):
                if verdict == 'FULL CUT':
                    verdict = 'INCONCLUSIVE'
                reasons.append(
                    'BEFORE saw victim IPv4 but DURING saw none — idle console or '
                    'traffic not attracted to this PC'
                )
            # FULL CUT requires evidence the victim was live (ping/ARP/MAC match).
            if verdict == 'FULL CUT' and victim_on_lan is not True:
                verdict = 'INCONCLUSIVE'
                reasons.append(
                    'stack looks armed but victim LAN presence was not confirmed '
                    '(ping/ARP) — rescan if this IP may be stale'
                )
        else:
            if not d_stack.get('forwarder_running') and not d_stack.get('mitm_armed'):
                verdict = 'NOT CUT'
                reasons.append('Percent Cut stack not armed')
            else:
                verdict = 'PARTIAL'
                reasons.append(
                    f'Percent Cut armed ({int(cut_pct) if cut_pct is not None else "?"}% cut) '
                    '— not a full offline / red-chain cut'
                )

    # AFTER restore checks
    if after is not None:
        if a_stack.get('use_windivert'):
            if a_stack.get('windivert_paused'):
                verdict = 'PARTIAL' if verdict == 'FULL CUT' else verdict
                reasons.append('AFTER: WinDivert still paused after OFF')
            else:
                reasons.append('AFTER: WinDivert not paused (restore look OK)')
        else:
            if a_stack.get('mitm_armed'):
                verdict = 'PARTIAL' if verdict in ('FULL CUT', 'INCONCLUSIVE') else verdict
                if verdict == 'NOT CUT':
                    pass
                else:
                    verdict = 'PARTIAL'
                reasons.append('AFTER: ARP MITM still armed — victim may stay cut')
            else:
                reasons.append('AFTER: ARP MITM cleared')
            if a_stack.get('forwarder_running'):
                verdict = 'PARTIAL'
                reasons.append('AFTER: forwarder still running')
            else:
                reasons.append('AFTER: forwarder cleared')
        if (
            a_sample.get('ok')
            and b_sample.get('ok')
            and int(b_sample.get('ipv4') or 0) >= 3
            and int(a_sample.get('ipv4') or 0) == 0
            and int(a_sample.get('arp_victim') or 0) == 0
        ):
            # Traffic may stay quiet if console kicked from game — warn only.
            reasons.append(
                'AFTER: no victim IPv4 vs BEFORE baseline (console idle/kicked, or still cut)'
            )

    # Cap verdict if host adapter was dead during cut.
    if d_host.get('settings_adapter_live') is False and verdict == 'FULL CUT':
        verdict = 'PARTIAL'
        reasons.append('cannot trust FULL CUT with dead Settings adapter')
    if victim_on_lan is False and verdict == 'FULL CUT':
        verdict = 'NOT CUT'
        reasons.append('cannot report FULL CUT for a victim that is not on the LAN')

    lines.append(f'>>> VERDICT: {verdict}')
    for r in reasons:
        lines.append(f'  - {r}')
    lines.append('')
    lines.append('Notes:')
    lines.append('  BEFORE = baseline on ZubCut NIC (Analysis ON keeps this fresh).')
    lines.append('  DURING = cut armed; victim IPv4 on this PC means MITM attracted traffic.')
    lines.append('  AFTER  = flow OFF; MITM/forwarder must clear so the victim recovers.')
    lines.append('  Instant Kill/Dupe/Lag is never delayed — Analysis runs around it.')
    lines.append('=====================================')

    return CutAnalysisReport(
        flow=flow,
        verdict=verdict,
        victim_ip=victim_ip,
        victim_mac=victim_mac,
        lines=lines,
        phases=phases,
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
