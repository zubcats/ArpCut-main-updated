"""Deep cut Analysis — verify Kill/Lag/Dupe/Percent Cut against the victim.

Runs off the click hot path (caller schedules after arm). Uses a short Npcap
sniff plus live MITM/forwarder/forwarding state to score FULL / PARTIAL / NOT CUT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class CutAnalysisReport:
    flow: str
    verdict: str  # FULL CUT | PARTIAL | NOT CUT | INCONCLUSIVE
    victim_ip: str
    victim_mac: str
    lines: List[str] = field(default_factory=list)
    report_path: Optional[str] = None

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
    seconds: float = 2.5,
) -> dict[str, Any]:
    """Capture a short sample; return packet class counts (best-effort)."""
    out: dict[str, Any] = {
        'ok': False,
        'error': '',
        'ipv4': 0,
        'ipv6': 0,
        'arp': 0,
        'arp_poison_like': 0,
        'total': 0,
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
    # ARP + IPv4 victim + any IPv6 (filter host for v6 is flaky on some Npcap builds).
    bpf = f'arp or host {victim_ip} or ip6'
    try:
        pkts = sniff(
            filter=bpf,
            iface=iface_guid,
            timeout=max(0.5, float(seconds)),
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
                    out['arp_poison_like'] += 1
                continue
            if pkt.haslayer(IPv6):
                # Only count if victim appears in addresses when present as IPv4-mapped-ish
                # or if we cannot map — count all IPv6 as possible bypass signal lightly.
                out['ipv6'] += 1
                continue
            # IPv4 host filter already scoped most frames; count remainder as ipv4.
            out['ipv4'] += 1
        except Exception:
            continue
    return out


def analyze_victim_cut(
    *,
    flow: str,
    victim_ip: str,
    victim_mac: str,
    gateway_mac: str = '',
    iface_guid: str = '',
    iface_name: str = '',
    seconds: float = 2.5,
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
) -> CutAnalysisReport:
    """
    Score whether the intended impairment is actually cutting the victim.

    ``expect_full_cut``: Kill / Dupe / Lag block phase. Percent Cut uses False.
    """
    flow = str(flow or 'Cut').strip() or 'Cut'
    victim_ip = str(victim_ip or '').strip()
    victim_mac = str(victim_mac or '').strip()
    lines: List[str] = []
    lines.append('======== ZubCut Cut Analysis ========')
    lines.append(f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}Z')
    lines.append(f'Flow: {flow}')
    lines.append(f'Victim: {victim_ip or "?"} ({victim_mac or "no MAC"})')
    lines.append(f'Adapter: {iface_name or "?"} ({iface_guid or "no guid"})')
    if gateway_mac:
        lines.append(f'Gateway MAC: {gateway_mac}')
    lines.append('')

    sample = _sniff_cut_sample(iface_guid, victim_ip, seconds=seconds)
    if sample.get('ok'):
        lines.append(
            f'[INFO] Capture sample ({seconds:g}s): total={sample["total"]} '
            f'ipv4≈{sample["ipv4"]} arp={sample["arp"]} ipv6={sample["ipv6"]} '
            f'arp↔victim={sample["arp_poison_like"]}'
        )
    else:
        lines.append(f'[WARN] Capture sample failed: {sample.get("error") or "unknown"}')

    if use_windivert:
        lines.append(
            f'[{"PASS" if windivert_running else "FAIL"}] WinDivert gate running'
        )
        lines.append(
            f'[{"PASS" if windivert_paused else "WARN"}] WinDivert pause/block armed'
        )
    else:
        lines.append(f'[{"PASS" if mitm_armed else "FAIL"}] ARP MITM armed (killer.killed)')
        lines.append(
            f'[{"PASS" if forwarder_running else "WARN"}] Npcap forwarder running'
        )
        if expect_full_cut:
            lines.append(
                f'[{"PASS" if forwarder_hard_drop else "WARN"}] Forwarder hard-drop (full cut)'
            )
        if cut_pct is not None:
            lines.append(f'[INFO] Percent Cut target: {int(cut_pct)}% cut')
        if ip_forwarding_on is True:
            lines.append('[FAIL] Windows IP forwarding ON (kernel may relay — partial cut)')
        elif ip_forwarding_on is False:
            lines.append('[PASS] Windows IP forwarding off')
        else:
            lines.append('[INFO] Windows IP forwarding not probed')

    # --- Verdict ---
    reasons: List[str] = []
    verdict = 'INCONCLUSIVE'

    if use_windivert:
        if not windivert_running:
            verdict = 'NOT CUT'
            reasons.append('WinDivert gate not running')
        elif expect_full_cut and not windivert_paused:
            verdict = 'PARTIAL'
            reasons.append('WinDivert running but not paused/blocked')
        elif windivert_paused or not expect_full_cut:
            verdict = 'FULL CUT' if expect_full_cut else 'PARTIAL'
            if not expect_full_cut:
                reasons.append('Percent Cut / shaping path (not a full offline cut)')
            else:
                reasons.append('WinDivert pause armed')
    else:
        if not mitm_armed:
            verdict = 'NOT CUT'
            reasons.append('ARP MITM not armed')
        elif expect_full_cut:
            if ip_forwarding_on is True:
                verdict = 'PARTIAL'
                reasons.append('IP forwarding still ON')
            if not forwarder_running:
                verdict = 'PARTIAL'
                reasons.append('Npcap forwarder not running (ARP-only — often no red chain)')
            elif not forwarder_hard_drop:
                verdict = 'PARTIAL'
                reasons.append('forwarder not in hard-drop mode')
            elif sample.get('ok') and int(sample.get('ipv4') or 0) == 0 and int(
                sample.get('arp_poison_like') or 0
            ) == 0:
                # MITM armed but nothing observed — may still be cut if console is idle,
                # or poison never attracted traffic.
                if verdict != 'PARTIAL':
                    verdict = 'INCONCLUSIVE'
                reasons.append(
                    'no victim IPv4/ARP seen on this NIC (idle console or traffic not attracted)'
                )
            else:
                if verdict != 'PARTIAL':
                    verdict = 'FULL CUT'
                    reasons.append('MITM armed, hard-drop forwarder live, forwarding off/ok')
            if sample.get('ok') and int(sample.get('ipv6') or 0) > 8:
                verdict = 'PARTIAL'
                reasons.append('notable IPv6 traffic during sample (possible bypass)')
        else:
            # Percent Cut — expect MITM + forwarder with partial pass.
            if not forwarder_running and not mitm_armed:
                verdict = 'NOT CUT'
                reasons.append('Percent Cut stack not armed')
            elif not forwarder_running:
                verdict = 'PARTIAL'
                reasons.append('MITM without live percent-cut forwarder')
            else:
                verdict = 'PARTIAL'
                reasons.append(
                    f'Percent Cut armed ({int(cut_pct) if cut_pct is not None else "?"}% cut) — '
                    'not a full offline / red-chain cut'
                )

    lines.append('')
    lines.append(f'>>> VERDICT: {verdict}')
    for r in reasons:
        lines.append(f'  - {r}')
    lines.append('')
    lines.append('Notes:')
    lines.append('  Seeing victim IPv4 on this PC during MITM is normal (traffic attracted).')
    lines.append('  FULL CUT needs hard-drop forwarder (or WinDivert pause) + forwarding off.')
    lines.append('  Analysis never delays Kill/Dupe/Lag click — it runs after arm.')
    lines.append('=====================================')

    # Unused locals kept for future MAC correlation (poison psrc/hwsrc checks).
    _ = (_norm_mac(local_mac), _norm_mac(gateway_mac))

    return CutAnalysisReport(
        flow=flow,
        verdict=verdict,
        victim_ip=victim_ip,
        victim_mac=victim_mac,
        lines=lines,
    )


def save_cut_analysis_report(report: CutAnalysisReport) -> Optional[Path]:
    """Write report under Desktop\\ZubCut Diagnostics. Returns path or None."""
    try:
        from tools.diag_paths import ensure_zubcut_diagnostics_dir
        from tools.diag_privacy import redact_ipv4s_in_text
    except Exception:
        return None
    try:
        folder = ensure_zubcut_diagnostics_dir()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        flow_slug = ''.join(ch if ch.isalnum() else '-' for ch in report.flow).strip('-') or 'cut'
        path = folder / f'ZubCut-Analysis-{flow_slug}-{stamp}.txt'
        body = '\n'.join(report.lines) + '\n'
        try:
            body = redact_ipv4s_in_text(body)
        except Exception:
            pass
        path.write_text(body, encoding='utf-8')
        report.report_path = str(path)
        return path
    except Exception:
        return None
