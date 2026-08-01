"""Privacy helpers for support diagnostic reports (screenshot-safe SUMMARY)."""
from __future__ import annotations

import re
from typing import Match

_IPV4_RE = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b'
)


def redact_ipv4(ip: str) -> str:
    """
    Redact an IPv4 with ``x`` masks while keeping host/setup cues.

    Examples:
      192.168.1.56      → 192.168.x.56
      192.168.137.2     → 192.168.137.x
      10.0.0.2          → 10.x.x.2
      169.254.10.20     → 169.254.x.x
      8.8.8.8           → x.x.x.8
    """
    s = str(ip or '').strip()
    m = re.fullmatch(
        r'(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})',
        s,
    )
    if not m:
        return s or '(ip)'
    a, b, c, d = (int(m.group(i)) for i in range(1, 5))
    if not all(0 <= x <= 255 for x in (a, b, c, d)):
        return '(ip)'
    if a == 192 and b == 168 and c == 137:
        return '192.168.137.x'
    if a == 169 and b == 254:
        return '169.254.x.x'
    if a == 127:
        return f'127.x.x.{d}'
    if a == 192 and b == 168:
        return f'192.168.x.{d}'
    if a == 10:
        return f'10.x.x.{d}'
    if a == 172 and 16 <= b <= 31:
        return f'172.x.x.{d}'
    if a == 100 and 64 <= b <= 127:
        return f'100.x.x.{d}'
    return f'x.x.x.{d}'


def same_ipv4_subnet(ip_a: str, ip_b: str) -> bool | None:
    """True when both IPv4s share a /24 (common home LAN check)."""
    def _parts(ip: str) -> tuple[int, int, int, int] | None:
        m = re.fullmatch(
            r'(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})',
            str(ip or '').strip(),
        )
        if not m:
            return None
        vals = tuple(int(m.group(i)) for i in range(1, 5))
        if not all(0 <= x <= 255 for x in vals):
            return None
        return vals  # type: ignore[return-value]

    pa, pb = _parts(ip_a), _parts(ip_b)
    if not pa or not pb:
        return None
    return pa[:3] == pb[:3]


def redact_ipv4s_in_text(text: str) -> str:
    """Replace every IPv4 in ``text`` with ``redact_ipv4`` form."""

    def _sub(match: Match[str]) -> str:
        return redact_ipv4(match.group(0))

    return _IPV4_RE.sub(_sub, text or '')
