"""Shared Admin PowerShell launch for Logs diagnostic tools."""
from __future__ import annotations

import os
import subprocess
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


def write_ps1_runner(dest: Path, text: str) -> Path:
    """
    Write a temp elevated-runner ``.ps1`` (UTF-8 BOM for Windows PowerShell 5.1).

    Reports stay under Desktop\\ZubCut Diagnostics; runners stay in ``%TEMP%\\ZubCut``.
    """
    body = text if isinstance(text, str) else str(text)
    if not body.strip().endswith('\n'):
        body = body.rstrip('\r\n') + '\n'
    # Normalize to LF in the file body; BOM marks UTF-8 for Windows PowerShell.
    body = body.replace('\r\n', '\n').replace('\r', '\n')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(('\ufeff' + body).encode('utf-8'))
    return dest


def _already_admin() -> bool:
    try:
        from tools.utils_gui import is_admin

        return bool(is_admin())
    except Exception:
        return False


def launch_ps1_elevated(
    script_path: Path,
    *,
    elevate=None,
    tool_label: str = 'Diagnostic',
) -> tuple[bool, str]:
    """
    Start ``script_path`` in Admin PowerShell.

    When ZubCut is already elevated, start PowerShell directly (no second UAC
    ``runas`` — that often fails silently for LAN/Hotspot path buttons).
    Otherwise use UAC elevation.

    Returns ``(ok, status_message)``. Does not place scripts in
    Desktop\\ZubCut Diagnostics — callers write reports there from inside the PS1.
    """
    if not sys.platform.startswith('win'):
        return False, f'{tool_label} is Windows-only.'
    script_s = str(script_path)
    if not script_s or not Path(script_s).is_file():
        return False, f'Could not prepare {tool_label}.'

    # Already Admin: run visible PowerShell without a nested runas.
    if elevate is None and _already_admin():
        try:
            subprocess.Popen(
                [
                    powershell_exe(),
                    '-NoProfile',
                    '-ExecutionPolicy',
                    'Bypass',
                    '-File',
                    script_s,
                ],
                cwd=str(Path(script_s).parent),
                close_fds=True,
            )
        except Exception as exc:
            return False, f'Could not start Admin PowerShell: {exc}'
        return (
            True,
            f'{tool_label} started in Admin PowerShell — '
            'screenshot the SUMMARY in Notepad '
            '(Desktop\\ZubCut Diagnostics) and send it to support.',
        )

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
