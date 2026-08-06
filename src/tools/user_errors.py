"""Sanitize text shown in error dialogs (ZC- codes, updater, sign-in)."""
from __future__ import annotations

import re

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
    'ZC-ADMIN': 'Administrator rights required — relaunch ZubCut elevated (UAC).',
    'ZC-IFACE': 'Selected adapter is missing or has no usable IPv4 — pick a live NIC in Settings.',
    'ZC-ROUTE': 'Victim is not on a local L2 path from this PC — check Wi‑Fi/Ethernet handoff.',
    'ZC-GWMAC': 'Router MAC unknown — ARP MITM cannot arm. Check Npcap + cable/Wi‑Fi driver.',
    'ZC-VMAC': 'Victim MAC unknown — ping the device once, then Rescan.',
    'ZC-FWD': 'Windows IP forwarding still on — Kill may lag instead of full cut. Relaunch as Admin.',
    'ZC-WD': 'WinDivert unavailable — Clumsy mode + Admin + bundle required for hotspot cut.',
    'ZC-WD-HVCI': 'WinDivert blocked by Memory Integrity / HVCI / Smart App Control — turn Core Isolation off, or set Smart App Control to Off (Windows Security → App & browser control; recent 24H2/25H2 can toggle SAC without reinstall).',
    'ZC-ICS': 'Hotspot/ICS path not ready — enable Mobile Hotspot; wait for 192.168.137.x or 192.168.173.x client.',
    'ZC-FW': 'Windows Firewall rule apply failed — check Admin and third-party firewall/AV.',
    'ZC-IPV6': 'IPv6 may bypass IPv4 ARP Kill (PS5 dual-stack) — use PC Mobile Hotspot, or disable IPv6 on the LAN NIC.',
    'ZC-WPA3': 'WPA3 Wi‑Fi often blocks ARP MITM — set the SSID to WPA2-Personal for LAN Kill.',
    'ZC-MLO': 'Wi‑Fi 7 MLO can break ARP MITM — disable multi-link on the router or use hotspot/Ethernet.',
    'ZC-ISOLATION': 'AP/client isolation (guest Wi‑Fi) can block ARP MITM — use Ethernet PC + console, or PC Mobile Hotspot.',
    'ZC-AV': 'Antivirus / Controlled Folder Access may block Npcap or WinDivert — allow ZubCut.',
}


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
    base = ERROR_CODES.get(key) or ERROR_CODES.get(code) or ''
    if not base:
        base = scrub_user_error_text(str(detail or key or 'Unknown error'))
        return f'{key}: {base}' if key else base
    msg = f'{key}: {base}'
    extra = scrub_user_error_text(str(detail or '').strip())
    if extra and extra.lower() not in msg.lower():
        msg = f'{msg} ({extra})'
    return msg
