"""Sanitize text shown in error dialogs (ZC- codes, updater, sign-in)."""
from __future__ import annotations

import re
from threading import Lock
from typing import Any, Iterable, Optional

_GITHUB_URL_RE = re.compile(
    r'https?://(?:www\.)?(?:api\.)?github(?:usercontent)?\.com\S*',
    re.IGNORECASE,
)

# Stable support codes for common failures (not crash refs — those stay ZC-XXXXXX).
# Keep messages short and actionable; never mention GitHub.
ERROR_CODES: dict[str, str] = {
    'ZC-NPCAP': 'Npcap missing or not loadable — install Npcap (WinPcap API-compatible mode).',
    'ZC-NPCAP-SVC': 'Npcap driver service is not running — reboot or reinstall Npcap.',
    'ZC-NPCAP-ADMIN': 'Npcap AdminOnly is ON — run ZubCut as Administrator, or reinstall Npcap without AdminOnly.',
    'ZC-WINPCAP': 'WinPcap/Win10Pcap is still installed — uninstall it, reboot, keep Npcap only.',
    'ZC-ADMIN': 'Administrator rights required — relaunch ZubCut elevated (UAC).',
    'ZC-IFACE': 'Selected adapter is missing or has no usable IPv4 — pick a live NIC in Settings.',
    'ZC-ROUTE': 'Victim is not on a local L2 path from this PC — check Wi‑Fi/Ethernet handoff.',
    'ZC-GWMAC': 'Router MAC unknown — ARP MITM cannot arm. Check Npcap + cable/Wi‑Fi driver.',
    'ZC-VMAC': 'Victim MAC unknown — ping the device once, then Rescan.',
    'ZC-FWD': 'Windows IP forwarding still on — Kill may lag instead of full cut. Relaunch as Admin.',
    'ZC-WD': 'WinDivert unavailable — Clumzy Mode + Admin + bundle required for hotspot cut.',
    'ZC-WD-HVCI': 'WinDivert blocked by Memory Integrity / HVCI / Smart App Control — turn Core Isolation off, or set Smart App Control to Off (Windows Security → App & browser control; recent 24H2/25H2 can toggle SAC without reinstall).',
    'ZC-ICS': 'Hotspot/ICS path not ready — enable Mobile Hotspot; wait for 192.168.137.x or 192.168.173.x client.',
    'ZC-FW': 'Windows Firewall rule apply failed — check Admin and third-party firewall/AV.',
    'ZC-IPV6': 'IPv6 may bypass IPv4 ARP Kill (PS5 dual-stack) — use PC Mobile Hotspot, or disable IPv6 on the LAN NIC.',
    'ZC-WPA3': 'WPA3 Wi‑Fi often blocks ARP MITM — set the SSID to WPA2-Personal for LAN Kill.',
    'ZC-MLO': 'Wi‑Fi 7 MLO can break ARP MITM — disable multi-link on the router or use hotspot/Ethernet.',
    'ZC-ISOLATION': 'AP/client isolation (guest Wi‑Fi) can block ARP MITM — use Ethernet PC + console, or PC Mobile Hotspot.',
    'ZC-AV': 'Antivirus / Controlled Folder Access may block Npcap or WinDivert — allow ZubCut.',
}

_LEVEL_RANK = {'ok': 0, 'info': 0, 'warn': 1, 'fail': 2, 'error': 2}
_zc_lock = Lock()
# code -> {code, level, source, message} — recent diagnostic observations for crash reports.
_zc_seen: dict[str, dict[str, str]] = {}
_ZC_SEEN_MAX = 40


def normalize_zc_code(code: str) -> str:
    """Return a registry ZC-* key, or '' if unknown / crash-ref shaped."""
    key = str(code or '').strip().upper()
    if not key:
        return ''
    if key in ERROR_CODES:
        return key
    # Reject random crash refs (ZC- + exactly 6 chars, not in the registry).
    if re.fullmatch(r'ZC-[A-Z0-9]{6}', key):
        return ''
    return ''


def note_zc_code(code: str, *, level: str = '', source: str = '') -> None:
    """Remember a diagnostic ZC code (best-effort; used by crash reporting)."""
    key = normalize_zc_code(code)
    if not key:
        return
    lvl = str(level or '').strip().lower()
    if lvl not in _LEVEL_RANK:
        lvl = 'warn'
    src = str(source or '').strip()[:40]
    msg = ERROR_CODES.get(key, '')
    with _zc_lock:
        prev = _zc_seen.get(key)
        if prev is not None and _LEVEL_RANK.get(prev.get('level', ''), 0) > _LEVEL_RANK.get(lvl, 0):
            # Keep the worse severity; refresh source if provided.
            if src and not prev.get('source'):
                prev['source'] = src
            return
        _zc_seen[key] = {
            'code': key,
            'level': lvl,
            'source': src or (prev or {}).get('source', ''),
            'message': msg,
        }
        if len(_zc_seen) > _ZC_SEEN_MAX:
            # Drop oldest insertion order (dict preserves order on 3.7+).
            for drop in list(_zc_seen.keys())[: len(_zc_seen) - _ZC_SEEN_MAX]:
                _zc_seen.pop(drop, None)


def note_zc_findings(findings: Iterable[Any], *, source: str = 'readiness') -> None:
    """Record codes from readiness (or similar) finding objects / dicts."""
    for f in findings or ():
        try:
            if isinstance(f, dict):
                code = f.get('code') or ''
                level = f.get('level') or ''
            else:
                code = getattr(f, 'code', '') or ''
                level = getattr(f, 'level', '') or ''
            if code:
                note_zc_code(str(code), level=str(level or ''), source=source)
        except Exception:
            continue


def latest_zc_codes() -> list[dict[str, str]]:
    """Snapshot of recently observed diagnostic codes (worst level first)."""
    with _zc_lock:
        rows = [dict(v) for v in _zc_seen.values()]
    rows.sort(
        key=lambda r: (
            -_LEVEL_RANK.get(str(r.get('level') or ''), 0),
            str(r.get('code') or ''),
        )
    )
    return rows


def zc_code_catalog() -> list[dict[str, str]]:
    """Full registry of support codes (for crash payload / Control Panel legend)."""
    return [{'code': k, 'message': v} for k, v in sorted(ERROR_CODES.items())]


def format_zc_codes_header(codes: Optional[Iterable[dict]] = None) -> str:
    """Compact ``zc_codes=ZC-NPCAP:fail,ZC-WPA3:warn`` line for crash logs."""
    rows = list(codes) if codes is not None else latest_zc_codes()
    parts = []
    for r in rows:
        code = str((r or {}).get('code') or '').strip()
        if not code:
            continue
        level = str((r or {}).get('level') or '').strip()
        parts.append(f'{code}:{level}' if level else code)
    return ','.join(parts)


def parse_zc_codes_header(log_text: str) -> list[dict[str, str]]:
    """Parse ``zc_codes=…`` from a crash log header (pending upload path)."""
    for line in (log_text or '').splitlines()[:40]:
        s = line.strip()
        if not s.lower().startswith('zc_codes='):
            continue
        raw = s.split('=', 1)[1].strip()
        if not raw or raw in ('—', '-', 'none'):
            return []
        out: list[dict[str, str]] = []
        for part in raw.split(','):
            token = part.strip()
            if not token:
                continue
            code, _, level = token.partition(':')
            key = normalize_zc_code(code) or str(code or '').strip().upper()
            if not key.startswith('ZC-'):
                continue
            lvl = level.strip().lower()
            out.append(
                {
                    'code': key,
                    'level': lvl if lvl in _LEVEL_RANK else '',
                    'source': 'log',
                    'message': ERROR_CODES.get(key, ''),
                }
            )
        return out
    return []


def scrub_user_error_text(text: str) -> str:
    """Remove GitHub URLs and branding from user-visible error strings."""
    s = str(text or '')
    s = _GITHUB_URL_RE.sub('the update server', s)
    s = re.sub(r'\bGitHub Releases\b', 'the official release', s, flags=re.IGNORECASE)
    s = re.sub(r'\bGitHub\b', 'the official update server', s, flags=re.IGNORECASE)
    return s


def safe_text_lines(text) -> list[str]:
    """Like str.splitlines() but never raises when text is None."""
    if text is None:
        return []
    return str(text).splitlines()


def format_build_version_hint() -> str:
    """Short build stamp for support dialogs (empty when running from source)."""
    try:
        from constants import APP_BUILD_COMMIT

        commit = str(APP_BUILD_COMMIT or '').strip()[:12]
    except Exception:
        commit = ''
    return f'\n\nBuild: {commit}' if commit else ''


def format_error_code(code: str, detail: str = '') -> str:
    """
    Format a stable ZubCut support code with optional detail.

    Example: ``ZC-NPCAP: Npcap missing... (detail)``
    """
    key = str(code or '').strip().upper()
    try:
        note_zc_code(key, level='fail', source='format_error_code')
    except Exception:
        pass
    base = ERROR_CODES.get(key) or ERROR_CODES.get(code) or ''
    if not base:
        base = scrub_user_error_text(str(detail or key or 'Unknown error'))
        return f'{key}: {base}' if key else base
    msg = f'{key}: {base}'
    extra = scrub_user_error_text(str(detail or '').strip())
    if extra and extra.lower() not in msg.lower():
        msg = f'{msg} ({extra})'
    return msg
