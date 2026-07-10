"""DPAPI helpers for Control Panel secrets at rest (Windows)."""

from __future__ import annotations

import base64
import os
import sys
from typing import Optional


def _dpapi_available() -> bool:
    return sys.platform.startswith('win')


def protect_secret(plain: str) -> str:
    """
    Encrypt a UTF-8 secret for the current Windows user (DPAPI).
    Returns ``dpapi:<b64>`` or the original string when DPAPI is unavailable.
    """
    text = str(plain or '')
    if not text or not _dpapi_available():
        return text
    if text.startswith('dpapi:'):
        return text
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        raw = text.encode('utf-8')
        blob_in = DATA_BLOB(len(raw), ctypes.cast(ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            'ZubCut',
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            return text
        try:
            encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
        return 'dpapi:' + base64.b64encode(encrypted).decode('ascii')
    except Exception:
        return text


def unprotect_secret(stored: str) -> str:
    """Decrypt a ``dpapi:`` blob, or return plaintext unchanged."""
    text = str(stored or '')
    if not text.startswith('dpapi:') or not _dpapi_available():
        return text
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        raw = base64.b64decode(text[6:].encode('ascii'))
        blob_in = DATA_BLOB(len(raw), ctypes.cast(ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            return ''
        try:
            plain = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
        return plain.decode('utf-8', errors='replace')
    except Exception:
        return ''


def protect_bytes(raw: bytes) -> bytes:
    """DPAPI-protect raw key material; returns plaintext bytes if unavailable."""
    data = bytes(raw or b'')
    if not data or not _dpapi_available():
        return data
    if data.startswith(b'DPAPI1:'):
        return data
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            'ZubCutKey',
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            return data
        try:
            encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
        return b'DPAPI1:' + encrypted
    except Exception:
        return data


def unprotect_bytes(stored: bytes) -> bytes:
    data = bytes(stored or b'')
    if not data.startswith(b'DPAPI1:') or not _dpapi_available():
        return data
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        raw = data[7:]
        blob_in = DATA_BLOB(len(raw), ctypes.cast(ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            return b''
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return b''


def is_dpapi_secret(stored: str) -> bool:
    return str(stored or '').startswith('dpapi:')


def is_dpapi_bytes(stored: bytes) -> bool:
    return bytes(stored or b'').startswith(b'DPAPI1:')


def rewrap_secret(stored: str) -> tuple[str, str]:
    """
    Decrypt (if needed) and re-encrypt with current-user DPAPI.
    Returns (new_stored, note). note is empty on success.
    """
    text = str(stored or '')
    if not text:
        return '', 'empty'
    plain = unprotect_secret(text) if is_dpapi_secret(text) else text
    if is_dpapi_secret(text) and not plain:
        return text, 'decrypt_failed'
    protected = protect_secret(plain)
    if _dpapi_available() and plain and not is_dpapi_secret(protected):
        return text, 'encrypt_failed'
    return protected, ''


def rewrap_bytes(stored: bytes) -> tuple[bytes, str]:
    data = bytes(stored or b'')
    if not data:
        return b'', 'empty'
    plain = unprotect_bytes(data) if is_dpapi_bytes(data) else data
    if is_dpapi_bytes(data) and not plain:
        return data, 'decrypt_failed'
    protected = protect_bytes(plain)
    if _dpapi_available() and plain and not is_dpapi_bytes(protected):
        return data, 'encrypt_failed'
    return protected, ''


def restrict_user_only_acl(path: str) -> None:
    """Best-effort: restrict a file to the current user on Windows."""
    if not path or not os.path.exists(path) or not sys.platform.startswith('win'):
        return
    try:
        import subprocess

        user = os.environ.get('USERNAME') or os.environ.get('USER') or ''
        if not user:
            return
        subprocess.run(
            ['icacls', path, '/inheritance:r', f'/grant:r', f'{user}:(R,W)'],
            check=False,
            capture_output=True,
            timeout=8,
        )
    except Exception:
        pass
