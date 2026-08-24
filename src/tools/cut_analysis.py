"""Deep cut Analysis — before / during / after victim + ZubCut-host checks.

Intended model (Kill/Dupe full-cut flows):
  BEFORE  — good connection (victim live on LAN)
  DURING  — full cut (victim WAN path severed; FAIL if connection still good)
  AFTER   — good connection restored after OFF

Never runs on the instant-cut hot path. Overall SUCCESS only when all three
phases match that model. Writes one privacy-masked report under
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


def _npcap_safe_bind_tokens(iface_guid: str, iface=None) -> list[str]:
    """Scapy/Npcap bind tokens that Npcap actually lists.

    A Windows InterfaceGuid that is not in ``get_if_list()`` (live-IP overlay)
    makes ``sniff()``/``arping()`` hang or steal the adapter, so Kill then
    logs ``Npcap forwarder unavailable`` and ``router MAC unknown``.
    """
    raw = str(iface_guid or '').strip()
    tokens: list[str] = []
    listed: set[str] = set()
    try:
        from tools.utils import (
            _extract_adapter_guid,
            _npcap_listed_guids,
            npcap_iface_tokens,
        )
    except Exception:
        return [raw] if raw else []
    try:
        listed = {str(g).upper() for g in (_npcap_listed_guids() or ()) if g}
    except Exception:
        listed = set()
    try:
        candidates = list(npcap_iface_tokens(iface, raw) or [])
    except Exception:
        candidates = []
    if raw and raw not in candidates:
        candidates.append(raw)
    for tok in candidates:
        s = str(tok or '').strip()
        if not s or s in tokens:
            continue
        guid = ''
        try:
            guid = str(_extract_adapter_guid(s) or '').upper()
        except Exception:
            guid = ''
        if listed and guid and guid not in listed:
            continue
        tokens.append(s)
    if tokens:
        return tokens
    if listed:
        guid = ''
        try:
            guid = str(_extract_adapter_guid(raw) or '').upper()
        except Exception:
            guid = ''
        if guid and guid not in listed:
            return []
    return [raw] if raw else []


def _sniff_cut_sample(
    iface_guid: str,
    victim_ip: str,
    *,
    seconds: float = 1.5,
    local_mac: str = '',
    gateway_ip: str = '',
    gateway_mac: str = '',
    victim_mac: str = '',
    iface=None,
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
    bind_tokens = _npcap_safe_bind_tokens(iface_guid, iface)
    if not bind_tokens:
        out['error'] = 'no Npcap bind token for Analysis sniff'
        return out
    try:
        from scapy.all import ARP, Ether, IP, IPv6, sniff  # type: ignore
    except Exception as exc:
        out['error'] = f'scapy unavailable: {exc}'
        return out
    bpf = f'arp or host {victim_ip} or ip6'
    pkts = None
    last_exc: Exception | None = None
    for tok in bind_tokens:
        try:
            pkts = sniff(
                filter=bpf,
                iface=tok,
                timeout=max(0.4, float(seconds)),
                store=True,
            )
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            continue
    if pkts is None:
        out['error'] = f'sniff failed: {last_exc}'
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
    local_mac: str = '',
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
        'local_mac': str(local_mac or ''),
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


def _fmt_host(host: dict, *, label: str, soft_midcut_lan_probes: bool = False) -> List[str]:
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
        if soft_midcut_lan_probes:
            lines.append(
                f'[INFO] {label} victim ping failed mid-cut — expected under hard-drop '
                '(not used as offline proof)'
            )
        else:
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
        if soft_midcut_lan_probes:
            lines.append(
                f'[INFO] {label} victim ARP cache empty/unstable mid-cut — expected under poison'
            )
        else:
            lines.append(f'[FAIL] {label} victim missing from ARP cache — stale row / not on LAN')
    if host.get('victim_mac_match') is True:
        lines.append(f'[PASS] {label} ARP MAC matches selected row')
    elif host.get('victim_mac_match') is False:
        if soft_midcut_lan_probes:
            lines.append(
                f'[INFO] {label} ARP MAC mismatch mid-cut '
                f'({sel_mac or "?"} vs {host.get("victim_arp_mac") or "(none)"}) — '
                'often ZubCut/gateway MAC during poison; ignored when WAN evidence is strong'
            )
        else:
            lines.append(
                f'[FAIL] {label} ARP MAC mismatch — selected '
                f'{sel_mac or "?"} vs live {host.get("victim_arp_mac") or "(none)"}'
            )
    if host.get('victim_on_lan') is True:
        lines.append(f'[PASS] {label} victim appears on LAN now')
    elif host.get('victim_on_lan') is False:
        if soft_midcut_lan_probes:
            lines.append(
                f'[INFO] {label} mid-cut LAN probe says offline — ignored; '
                'using BEFORE + victim WAN→us / drops instead'
            )
        else:
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
        if str(label).strip().upper() == 'AFTER':
            lines.append(
                f'[INFO] {label} Windows IP forwarding on'
            )
        else:
            lines.append(f'[FAIL] {label} Windows IP forwarding ON')
    elif fwd is False:
        lines.append(f'[PASS] {label} Windows IP forwarding off')
    if host.get('admin_ok') is True:
        lines.append(f'[PASS] {label} running elevated')
    elif host.get('admin_ok') is False:
        lines.append(f'[WARN] {label} not elevated')
    return lines


def _fmt_stack(
    stack: dict, *, label: str, expect_full_cut: bool, expect_cleared: bool = False
) -> List[str]:
    lines: List[str] = []
    if expect_cleared:
        if stack.get('use_windivert'):
            lines.append(
                f'[{"PASS" if not stack.get("windivert_paused") else "FAIL"}] '
                f'{label} WinDivert restored (not paused)'
            )
            return lines
        lines.append(
            f'[{"PASS" if not stack.get("mitm_armed") else "FAIL"}] '
            f'{label} ARP MITM cleared'
        )
        if stack.get('forwarder_hard_drop'):
            lines.append(
                f'[FAIL] {label} forwarder still in hard-drop after OFF'
            )
        elif stack.get('forwarder_running'):
            lines.append(
                f'[FAIL] {label} Npcap forwarder still running after OFF'
            )
        else:
            lines.append(
                f'[PASS] {label} Npcap forwarder stopped'
            )
        return lines
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
    # BEFORE offline wins over mid-cut ARP pollution on a ghost IP.
    if b_host.get('victim_on_lan') is False:
        victim_on_lan = False
    else:
        victim_on_lan = host.get('victim_on_lan')
        if victim_on_lan is None:
            victim_on_lan = b_host.get('victim_on_lan')
    use_wd = bool(stack.get('use_windivert'))
    severed = _victim_severance_evidence(stack, sample)
    mitm_path_armed = bool(
        stack.get('mitm_armed')
        or (use_wd and stack.get('windivert_running') and stack.get('windivert_paused'))
    )
    midcut_ok = _midcut_lan_probe_expected_degraded(
        host=host,
        before_host=b_host,
        stack=stack,
        sample=sample,
        before_live=b_host.get('victim_on_lan') is True,
        severed=severed,
        mitm_path_armed=mitm_path_armed,
    )
    # For deep dive: mid-cut probe fail with strong cut evidence counts as identity OK.
    victim_identity_ok = victim_on_lan is True or midcut_ok
    checks: List[Tuple[str, bool]] = [
        (
            'Victim identity OK (BEFORE live + LAN probe, or mid-cut degraded under hard-drop)',
            victim_identity_ok,
        ),
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
    checks.append(
        (
            'Victim identity held (BEFORE live / wire evidence — not ZubCut-only view)',
            victim_identity_ok,
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
    # L2 is opened on Kill click — a closed socket during Analysis baseline is
    # normal, not proof the adapter is broken.
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
        notes.append('BEFORE expects good connection — victim confirmed on LAN (ping/ARP)')
    else:
        fails.append(
            'BEFORE expects good connection — victim LAN presence not confirmed before cut'
        )
    if host.get('victim_mac_match') is False:
        fails.append('ARP MAC does not match selected row (stale/ghost identity)')
    if not (ps.sample or {}).get('ok'):
        notes.append('BEFORE traffic sample failed (host checks still apply)')
    return PhaseResult(PHASE_BEFORE, not fails, fails, notes)


def _stale_offline_victim_message(
    *hosts: dict, victim_ip: str = ''
) -> Tuple[bool, str, str]:
    """
    Detect selected IP was not a live LAN victim (ghost/stale row).

    Returns (is_stale, message, live_at_ip).
    """
    live_at = ''
    note = ''
    sel = str(victim_ip or '').strip()
    saw_offline = False
    for host in hosts:
        if not host:
            continue
        if host.get('victim_on_lan') is False:
            saw_offline = True
        if not live_at:
            live_at = str(host.get('victim_live_ip') or '').strip()
        if not note:
            note = str(host.get('victim_liveness_note') or '').strip()
        if not sel:
            sel = str(host.get('selected_victim_ip') or '').strip()
        # Pre-cut MAC mismatch with empty ARP is classic stale table row.
        if host.get('victim_mac_match') is False and host.get('victim_in_arp') is False:
            saw_offline = True
    # AFTER ping success means the selected IP was live (PS5 often fails ping
    # BEFORE when ARP is cold or Analysis sniffed a GUID Npcap does not list).
    after_host = hosts[2] if len(hosts) >= 3 else None
    if after_host and after_host.get('victim_ping_ok') is True:
        return False, '', live_at
    if not saw_offline:
        return False, '', live_at
    if note:
        msg = note
    elif live_at and sel and live_at != sel:
        msg = (
            f'{sel} is offline / not the live PS5 — this device is now at {live_at}. '
            'Rescan and select that row (not a valid cut test on the stale IP).'
        )
    elif sel:
        msg = (
            f'{sel} was not on LAN before the cut — stale/ghost IP, not a live PS5. '
            'Rescan and pick the active PlayStation row.'
        )
    else:
        msg = (
            'Selected victim was not on LAN before the cut — stale/ghost IP, '
            'not a valid cut test.'
        )
    return True, msg, live_at


def _midcut_lan_probe_expected_degraded(
    *,
    host: dict,
    before_host: dict,
    stack: dict,
    sample: dict,
    before_live: bool,
    severed: bool,
    mitm_path_armed: bool,
) -> bool:
    """
    True when mid-cut ping/ARP failure is an expected hard-drop MITM artifact.

    Successful Kill/Dupe often:
      - drops ICMP so ZubCut's ping to the PS5 fails
      - pollutes this PC's ARP cache (victim IP → ZubCut/gateway MAC)
    while the wire still shows victim WAN traffic hitting us and being dropped.
    That must not score as NOT CUT / offline victim.
    """
    if not before_live or not severed or not mitm_path_armed:
        return False
    if host.get('victim_on_lan') is True and host.get('victim_mac_match') is not False:
        return False
    # Strong wire proof the selected IP is still the victim in path.
    if int((sample or {}).get('victim_wan_out_to_us') or 0) <= 0 and int(
        stack.get('fwd_packets_dropped') or 0
    ) <= 0:
        return False
    return True


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

    # Prefer BEFORE liveness. Mid-cut ARP for a BEFORE-offline IP is often poison/cache
    # pollution — do not treat that as proof the selected row is the live PS5.
    stale, stale_msg, _live_at = _stale_offline_victim_message(
        b_host, host, victim_ip=str(b_host.get('selected_victim_ip') or '')
    )
    if stale and b_host.get('victim_on_lan') is False:
        fails.append(stale_msg)
        if stack.get('sample_window_ok') is False:
            notes.append(
                'DURING window also missed (cut already OFF) — secondary; '
                'primary issue is stale/offline selected IP, not Dupe timing'
            )
        if host.get('victim_on_lan') is True:
            notes.append(
                'ARP appeared during/after the attempt — do not trust that as the live PS5 '
                'when BEFORE already showed this IP offline'
            )
        verdict = 'NOT CUT'
        return PhaseResult(PHASE_DURING, False, fails, notes), verdict

    victim_on_lan = host.get('victim_on_lan')
    if victim_on_lan is None:
        victim_on_lan = b_host.get('victim_on_lan')
    before_live = b_host.get('victim_on_lan') is True
    use_wd = bool(stack.get('use_windivert'))
    bypass = _victim_wan_bypass(sample)
    severed = _victim_severance_evidence(stack, sample)
    mitm_path_armed = bool(
        stack.get('mitm_armed')
        or (use_wd and stack.get('windivert_running') and stack.get('windivert_paused'))
    )
    # Hard-drop MITM often breaks ZubCut→victim ping and pollutes this PC's ARP cache
    # (victim IP may briefly map to ZubCut/gateway MAC). That is NOT "PS5 offline".
    midcut_probe_degraded = _midcut_lan_probe_expected_degraded(
        host=host,
        before_host=b_host,
        stack=stack,
        sample=sample,
        before_live=before_live,
        severed=severed,
        mitm_path_armed=mitm_path_armed,
    )

    if host.get('settings_adapter_live') is False:
        fails.append('Settings adapter not live during cut')
    if host.get('ip_forwarding_on') is True and expect_full_cut and not stack.get('use_windivert'):
        fails.append('Windows IP forwarding ON during cut (kernel can relay = partial)')

    if victim_on_lan is False:
        if midcut_probe_degraded:
            notes.append(
                'mid-cut ping/ARP from ZubCut failed — expected under hard-drop MITM '
                '(ICMP/ARP view is degraded while victim WAN is being dropped). '
                'BEFORE was live; wire shows victim WAN→us / forwarder drops.'
            )
            arp_m = _norm_mac(str(host.get('victim_arp_mac') or ''))
            local_m = _norm_mac(str(host.get('local_mac') or ''))
            if arp_m and local_m and arp_m == local_m:
                notes.append(
                    'ARP cache lists ZubCut MAC for the victim IP during poison — '
                    'expected pollution, not a different device'
                )
            elif host.get('victim_mac_match') is False:
                notes.append(
                    'ARP MAC mismatch during cut is unreliable under poison; '
                    'identity taken from BEFORE + victim WAN traffic evidence'
                )
            victim_on_lan = True  # identity OK via BEFORE + wire, not mid-cut probes
        else:
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
        if midcut_probe_degraded:
            victim_on_lan = True
            notes.append(
                'mid-cut LAN presence inconclusive — using BEFORE + WAN cut evidence instead'
            )
        else:
            fails.append('victim on-LAN not confirmed during cut (ping/ARP)')

    # Missed sample window (Dupe too short / OFF before DURING settled).
    if expect_full_cut and stack.get('sample_window_ok') is False:
        fails.append(
            'DURING sample started after the cut already turned OFF — increase hold/Dupe '
            'duration to at least 8000 ms (5s is often too short once arm + settle + sniff run)'
        )
        verdict = 'INCONCLUSIVE'
        return PhaseResult(PHASE_DURING, False, fails, notes), verdict

    # Identity for FULL CUT: BEFORE live + (mid-cut LAN OK OR degraded-but-evidenced).
    if expect_full_cut and victim_on_lan is True and not midcut_probe_degraded:
        notes.append(
            'victim still visible on LAN during cut (ZubCut is not just blocking its own view)'
        )
    elif expect_full_cut and midcut_probe_degraded:
        notes.append(
            'victim identity held from BEFORE + live WAN cut evidence '
            '(mid-cut ping/ARP intentionally ignored)'
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
                    'DURING expects full cut — connection still GOOD via real gateway '
                    f'(bypass={int(sample.get("victim_wan_bypass_gw") or 0)}, '
                    f'returnBypass={int(sample.get("wan_return_bypass") or 0)}) — '
                    'FAIL (poison incomplete / wrong NIC)'
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
                    'DURING expects full cut — connection still looks GOOD / unproven '
                    '(need victim wan→us packets being dropped and/or forwarder drops; '
                    'poison ARP alone does NOT prove a cut). Keep the console in a game '
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
                    'DURING full cut OK — victim WAN path severed (wan→us / forwarder drops), '
                    'no gateway bypass; connection is NOT good during the cut (as required)'
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


def _eval_after(
    ps: Optional[PhaseSample],
    *,
    before: Optional[PhaseSample] = None,
    expect_full_cut: bool = True,
) -> PhaseResult:
    """AFTER must restore a good connection (inverse of DURING full cut)."""
    if ps is None:
        return PhaseResult(PHASE_AFTER, False, ['AFTER phase missing'])
    stack = ps.stack or {}
    host = ps.host or {}
    b_host = (before.host if before else {}) or {}
    fails: List[str] = []
    notes: List[str] = []
    if stack.get('use_windivert'):
        if stack.get('windivert_paused'):
            fails.append('WinDivert still paused after OFF — connection not restored')
        else:
            notes.append('WinDivert not paused after OFF')
    else:
        if stack.get('mitm_armed'):
            fails.append('ARP MITM still armed after OFF — connection not restored')
        else:
            notes.append('ARP MITM cleared')
        if stack.get('forwarder_hard_drop'):
            fails.append('forwarder still in hard-drop after OFF — connection not restored')
        elif stack.get('forwarder_running'):
            fails.append('Npcap forwarder still running after OFF — connection not restored')
        else:
            notes.append('forwarder cleared')

    # AFTER expects good connection again (especially when BEFORE had one).
    if host.get('victim_on_lan') is True:
        notes.append('AFTER expects good connection — victim reachable on LAN again')
    elif host.get('victim_on_lan') is False:
        if expect_full_cut and b_host.get('victim_on_lan') is True:
            fails.append(
                'AFTER expects good connection — victim still unreachable after OFF '
                '(restore failed / cut stuck)'
            )
        else:
            fails.append(
                'AFTER expects good connection — victim not on LAN after OFF'
            )
    elif expect_full_cut and b_host.get('victim_on_lan') is True:
        fails.append(
            'AFTER expects good connection — victim LAN presence not confirmed after OFF'
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
    after_r = _eval_after(after, before=before, expect_full_cut=expect_full_cut)

    phase_results = {
        PHASE_BEFORE: before_r,
        PHASE_DURING: during_r,
        PHASE_AFTER: after_r,
    }

    b_host = (before.host if before else {}) or {}
    d_host = (during.host if during else {}) or {}
    a_host = (after.host if after else {}) or {}
    stale, stale_msg, live_at = _stale_offline_victim_message(
        b_host, d_host, a_host, victim_ip=victim_ip
    )
    # Stale/ghost IP dominates: this was never a valid cut test.
    if stale and b_host.get('victim_on_lan') is False:
        verdict = 'NOT CUT'

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
    if stale and b_host.get('victim_on_lan') is False:
        overall = 'FAIL'
        verdict = 'NOT CUT'

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
            '  BEFORE good connection → DURING full cut → AFTER good connection.'
            if expect_full_cut
            else '  Percent Cut path armed and restored cleanly.'
        )
    elif stale and b_host.get('victim_on_lan') is False:
        lines.append('  OVERALL RESULT:  FAIL')
        lines.append('  Selected IP is NOT a live PS5 on LAN — not a valid cut test.')
        if live_at and live_at != victim_ip:
            lines.append(f'  Same device appears live at {live_at} — rescan and use that row.')
        elif stale_msg:
            lines.append(f'  {stale_msg}')
    else:
        lines.append('  OVERALL RESULT:  FAIL')
        lines.append(
            '  Did not match BEFORE=good / DURING=full cut / AFTER=good — see FAIL sections.'
            if expect_full_cut
            else '  The cut DID NOT fully work — see FAIL sections below.'
        )
    lines.append('#' * 64)
    lines.append('')
    lines.append(f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}Z')
    lines.append(f'Flow: {flow}')
    lines.append(f'Victim: {victim_ip or "?"} ({victim_mac or "no MAC"})')
    if live_at and live_at != victim_ip:
        lines.append(f'Live IP for this MAC (if known): {live_at}')
    if expect_full_cut:
        lines.append(
            'Expected: BEFORE=good connection | DURING=full cut | AFTER=good connection'
        )
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
        soft_midcut = False
        if ps.phase == PHASE_DURING:
            soft_midcut = any(
                'mid-cut ping/ARP' in n or 'mid-cut LAN presence' in n for n in (pr.notes or [])
            )
        lines.extend(
            _fmt_host(ps.host or {}, label=ps.phase, soft_midcut_lan_probes=soft_midcut)
        )
        lines.extend(_fmt_sample(ps.sample or {}, label=f'{ps.phase} victim traffic'))
        if ps.phase in (PHASE_DURING, PHASE_AFTER):
            lines.extend(
                _fmt_stack(
                    ps.stack or {},
                    label=ps.phase,
                    expect_full_cut=expect_full_cut if ps.phase == PHASE_DURING else False,
                    expect_cleared=ps.phase == PHASE_AFTER,
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
    if stale and b_host.get('victim_on_lan') is False:
        lines.append(
            '  Meaning: selected IP was not a live PS5 — rescan and cut the active row'
            + (f' ({live_at})' if live_at and live_at != victim_ip else '')
            + '.'
        )
    elif overall == 'FAIL':
        lines.append(
            '  Meaning: need BEFORE good connection, DURING full cut (fail if still connected), '
            'AFTER good connection restored.'
            if expect_full_cut
            else '  Meaning: cut did not work (or was only partial / not proven).'
        )
    else:
        lines.append(
            '  Meaning: BEFORE good → DURING full cut (WAN severed) → AFTER good again.'
            if expect_full_cut
            else '  Meaning: intended % cut path OK.'
        )
    for r in reasons:
        lines.append(f'  - {r}')
    lines.append('')
    lines.append('Phase model (Kill/Dupe):')
    lines.append('  BEFORE — good connection (victim live on LAN)')
    lines.append('  DURING — full cut (FAIL if connection still good / bypass / no drops)')
    lines.append('  AFTER  — good connection restored (victim reachable; MITM cleared)')
    lines.append('DURING full-cut proof:')
    lines.append('  sample window still ON (Dupe/hold ≥8000 ms recommended for Analysis)')
    lines.append('  ARP MITM armed + Npcap forwarder hard-drop 0% (red chain)')
    lines.append('  Windows IP forwarding OFF')
    lines.append('  victim WAN attempts hit this PC (wan→us) and/or forwarder drops > 0')
    lines.append('  NO victim WAN bypass via real gateway MAC (out or return)')
    lines.append('  mid-cut ZubCut ping/ARP fail is OK (hard-drop noise) — not used as "offline"')
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
