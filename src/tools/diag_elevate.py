"""Shared Admin PowerShell launch for Logs diagnostic tools."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def powershell_exe() -> str:
    system_root = os.environ.get('SystemRoot') or os.environ.get('WINDIR') or r'C:\Windows'
    candidate = os.path.join(
        system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'
    )
    if os.path.isfile(candidate):
        return candidate
    return 'powershell.exe'


def launch_ps1_elevated(
    script_path: Path,
    *,
    elevate=None,
    tool_label: str = 'Diagnostic',
) -> tuple[bool, str]:
    """
    Start ``script_path`` in Admin PowerShell via UAC.

    Returns ``(ok, status_message)``. Does not place scripts in
    Desktop\\ZubCut Diagnostics — callers write reports there from inside the PS1.
    """
    if not sys.platform.startswith('win'):
        return False, f'{tool_label} is Windows-only.'
    script_s = str(script_path)
    if not script_s or not Path(script_s).is_file():
        return False, f'Could not prepare {tool_label}.'
    params = (
        '-NoProfile -ExecutionPolicy Bypass -File '
        + '"'
        + script_s.replace('"', '')
        + '"'
    )
    try:
        if elevate is None:
            from tools.utils_gui import spawn_windows_elevated as elevate
        ok = bool(elevate(powershell_exe(), params))
    except Exception as exc:
        return False, f'Could not start Admin PowerShell: {exc}'
    if not ok:
        return (
            False,
            f'{tool_label} cancelled or failed to elevate — approve the UAC prompt.',
        )
    return (
        True,
        f'{tool_label} started in Admin PowerShell — '
        'screenshot the SUMMARY in Notepad '
        '(Desktop\\ZubCut Diagnostics) and send it to support.',
    )
