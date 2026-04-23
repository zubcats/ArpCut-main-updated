"""
Compact offline "sign-in code": zlib-compressed signed license JSON, base64url.
Users paste this once with their account name + password (no JSON file).
"""

from __future__ import annotations

import base64
import binascii
import json
import zlib
from typing import Any

_TOKEN_PREFIX = 'ZC1'  # ZubCut v1 marker so we don't mis-decode random strings


def encode_activation_token(doc: dict[str, Any]) -> str:
    """Encode {"payload": {...}, "signature": "..."} as a single pasteable string."""
    raw = json.dumps(doc, separators=(',', ':')).encode('utf-8')
    comp = zlib.compress(raw, level=9)
    body = base64.urlsafe_b64encode(comp).decode('ascii').rstrip('=')
    return f'{_TOKEN_PREFIX}{body}'


def decode_activation_token(token: str) -> dict[str, Any] | None:
    s = ''.join(str(token or '').split())
    if not s.startswith(_TOKEN_PREFIX):
        return None
    body = s[len(_TOKEN_PREFIX) :]
    pad = '=' * (-len(body) % 4)
    try:
        comp = base64.urlsafe_b64decode(body + pad)
        raw = zlib.decompress(comp)
        data = json.loads(raw.decode('utf-8'))
    except (ValueError, json.JSONDecodeError, zlib.error, binascii.Error, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data
