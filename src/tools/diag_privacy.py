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


def same_ipv4_subnet(
    ip_a: str,
    ip_b: str,
    *,
    prefix_len: int = 24,
) -> bool | None:
    """
    True when both IPv4s share a network of ``prefix_len``.

    Default remains /24 (common home LAN). Pass the live interface prefix
    (e.g. 23/22/16) when known so non-/24 LANs are not false-failed.
    """
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
    try:
        plen = int(prefix_len)
    except Exception:
        plen = 24
    if plen < 0 or plen > 32:
        plen = 24
    # Fast path for the historical /24 check.
    if plen == 24:
        return pa[:3] == pb[:3]
    try:
        import ipaddress

        net = ipaddress.IPv4Network(
            f'{pa[0]}.{pa[1]}.{pa[2]}.{pa[3]}/{plen}',
            strict=False,
        )
        other = ipaddress.IPv4Address(f'{pb[0]}.{pb[1]}.{pb[2]}.{pb[3]}')
        return other in net
    except Exception:
        # Masked integer compare fallback.
        mask = (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF if plen else 0
        a = (pa[0] << 24) | (pa[1] << 16) | (pa[2] << 8) | pa[3]
        b = (pb[0] << 24) | (pb[1] << 16) | (pb[2] << 8) | pb[3]
        return (a & mask) == (b & mask)


def redact_ipv4s_in_text(text: str) -> str:
    """Replace every IPv4 in ``text`` with ``redact_ipv4`` form."""

    def _sub(match: Match[str]) -> str:
        return redact_ipv4(match.group(0))

    return _IPV4_RE.sub(_sub, text or '')
