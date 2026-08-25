"""Test package bootstrap.

ZubCut does not call nmap.exe. Importing Scapy on Windows loads Npcap.
Scapy may then spawn ``WlanHelper.exe`` or ``Start-Process -Verb RunAs``
to start the Npcap service. Those binaries are signed by the Nmap Project,
so Windows shows an Nmap UAC prompt during local ``python -m unittest``
runs — not when using ZubCut.exe.

Block those child processes so agent test runs cannot pop UAC.
"""
from __future__ import annotations

import subprocess

_BLOCK_NEEDLES = (
    'wlanhelper',
    'nmap.exe',
    '\\nmap\\',
    '/nmap/',
    'verb runas',
    'npcap-1.',
    'sc start npcap',
    'sc start npf',
    'sc stop npcap',
    'restart-service -name npcap',
)

_orig_popen = subprocess.Popen


def _cmd_text(cmd) -> str:
    if isinstance(cmd, (list, tuple)):
        return ' '.join(str(x) for x in cmd)
    return str(cmd or '')


def _popen_no_nmap_uac(cmd, *args, **kwargs):
    text = _cmd_text(cmd).lower()
    if any(needle in text for needle in _BLOCK_NEEDLES):
        raise FileNotFoundError('blocked Npcap/Nmap UAC spawn in tests')
    return _orig_popen(cmd, *args, **kwargs)


subprocess.Popen = _popen_no_nmap_uac  # type: ignore[misc]
