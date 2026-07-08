"""
Automatic Windows capture-stack maintenance (Npcap bindings, Win10Pcap, NIC power).

Replaces manual Fix-ZubCut-*.ps1 scripts — runs silently during normal app warmup.
Requires Administrator for binding/power changes; no-ops safely when not elevated.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time

_maintain_lock = threading.Lock()
_maintain_last_mono = 0.0


def _is_admin() -> bool:
    if not sys.platform.startswith('win'):
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _safe_adapter_name(name: str) -> str:
    """Adapter friendly names are alphanumeric + punctuation; strip anything shell-risky."""
    name = str(name or '').strip()
    if not name or name == 'NULL':
        return ''
    if not re.fullmatch(r'[\w .()\-#]+', name, flags=re.ASCII):
        return ''
    return name.replace("'", "''")


def _run_powershell(script: str) -> None:
    if not script.strip():
        return
    try:
        from tools.utils import run_command

        run_command(
            [
                'powershell.exe',
                '-NoProfile',
                '-NonInteractive',
                '-ExecutionPolicy',
                'Bypass',
                '-Command',
                script,
            ],
            shell=False,
            timeout=45,
        )
    except Exception:
        pass


def _disable_pcie_aspm() -> None:
    """System-wide PCIe ASPM off — reduces first-packet wake latency after driver churn."""
    try:
        from tools.utils import run_command

        sub = '501a4d13-42af-4429-9fd1-a8218c268e20'
        setting = 'ee12f906-d277-404b-b6da-e5fa1a576df5'
        for flag in ('/SETACVALUEINDEX', '/SETDCVALUEINDEX'):
            run_command(
                ['powercfg', flag, 'SCHEME_CURRENT', sub, setting, '0'],
                shell=False,
                timeout=15,
            )
        run_command(['powercfg', '/SETACTIVE', 'SCHEME_CURRENT'], shell=False, timeout=15)
    except Exception:
        pass


def maintain_windows_capture_stack(
    *,
    iface_name: str = '',
    force: bool = False,
    min_interval_s: float = 300.0,
) -> None:
    """
    Keep Npcap on the right adapter and reduce NIC wake-up delay before MITM.

    Called from ZubCut startup / warmup — never surfaces external scripts to users.
    """
    if not sys.platform.startswith('win'):
        return
    global _maintain_last_mono
    now = time.monotonic()
    with _maintain_lock:
        if not force and _maintain_last_mono > 0.0 and now - _maintain_last_mono < min_interval_s:
            return
        _maintain_last_mono = now

    if not _is_admin():
        return

    active = _safe_adapter_name(iface_name)
    active_clause = f"$active = '{active}'" if active else '$active = $null'

    ps = f"""
$ErrorActionPreference = 'SilentlyContinue'
{active_clause}
Get-NetAdapter | ForEach-Object {{
  $n = $_.Name
  $bind = Get-NetAdapterBinding -Name $n -ComponentID 'INSECURE_NPCAP' -ErrorAction SilentlyContinue
  if ($bind -and $bind.Enabled -and $_.Status -ne 'Up') {{
    Disable-NetAdapterBinding -Name $n -ComponentID 'INSECURE_NPCAP' | Out-Null
  }}
}}
$targets = @()
if ($active) {{
  $one = Get-NetAdapter -Name $active -ErrorAction SilentlyContinue
  if ($one) {{ $targets = @($one) }}
}}
if (-not $targets) {{
  $targets = @(Get-NetAdapter | Where-Object {{ $_.Status -eq 'Up' }})
}}
foreach ($a in $targets) {{
  $w = Get-NetAdapterBinding -Name $a.Name -ComponentID 'Win10Pcap' -ErrorAction SilentlyContinue
  if ($w -and $w.Enabled) {{
    Disable-NetAdapterBinding -Name $a.Name -ComponentID 'Win10Pcap' | Out-Null
  }}
  Set-NetAdapterPowerManagement -Name $a.Name `
    -AllowComputerToTurnOffDevice Disabled `
    -WakeOnMagicPacket Disabled `
    -WakeOnPattern Disabled `
    -DeviceSleepOnDisconnect Disabled `
    -ErrorAction SilentlyContinue | Out-Null
}}
"""
    _run_powershell(ps)
    _disable_pcie_aspm()


def schedule_windows_capture_maintenance(
    *,
    iface_name: str = '',
    force: bool = False,
    prewarm=None,
) -> None:
    """Background maintenance + optional Killer.prewarm_l2_socket callback."""

    def _work() -> None:
        try:
            maintain_windows_capture_stack(iface_name=iface_name, force=force)
        except Exception:
            pass
        if callable(prewarm):
            try:
                prewarm()
            except Exception:
                pass

    try:
        from tools.crash_feedback import safe_daemon_target

        threading.Thread(
            target=safe_daemon_target(_work),
            name='zubcut-win-capture-maintain',
            daemon=True,
        ).start()
    except Exception:
        pass
