"""
Automatic Windows capture-stack maintenance (Npcap bindings, Win10Pcap, NIC power).

Runs silently during normal app warmup — users never run external Fix/Repair scripts.
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
            timeout=60,
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


def ensure_home_lan_mitm_forwarding_off() -> None:
    """
    Home LAN Kill/Lag/Dupe cut requires kernel IP forwarding OFF when no forwarder owns relay.
    Replaces manual Repair-ZubCut-Home-Lan-Mitm.ps1.

    Skip when Clumsy/hotspot is on: disabling IPEnableRouter + per-iface forwarding
    drops PS5 internet while Mobile Hotspot / Sharing still look enabled.

    Detect live SoftAP (192.168.137.1 / 173.1), not only the Clumsy checkbox —
    cold start clears clumsy_mode before this runs.
    """
    if not sys.platform.startswith('win') or not _is_admin():
        return
    try:
        from tools.clumsy_inline import ics_forwarding_must_stay_on

        if ics_forwarding_must_stay_on():
            return
    except Exception:
        pass
    try:
        from networking.killer import disable_ip_forwarding

        # Blocking: finish before the user can Kill (hot path stays non-blocking).
        disable_ip_forwarding(blocking=True)
    except Exception:
        pass


def _apply_intel_ethernet_low_latency(adapter_name: str) -> None:
    """
    Intel I219 / Ethernet Connection low-latency profile after driver reinstalls.
    Replaces Fix-ZubCut-Ethernet-Latency.ps1 and Fix-ZubCut-Kill-Delay.ps1 NIC tuning.
    """
    safe = _safe_adapter_name(adapter_name)
    if not safe:
        return

    ps = f"""
$ErrorActionPreference = 'SilentlyContinue'
$adapter = Get-NetAdapter -Name '{safe}' -ErrorAction SilentlyContinue
if (-not $adapter) {{ return }}
if ($adapter.InterfaceDescription -notmatch 'I219|Ethernet Connection') {{ return }}

# RegistryKeyword is locale-proof (DisplayName is translated on DE/FR/ES Windows).
function Set-ByKeyword($keyword, $values) {{
  foreach ($v in $values) {{
    try {{
      Set-NetAdapterAdvancedProperty -Name $adapter.Name -RegistryKeyword $keyword -DisplayValue $v -NoRestart -ErrorAction Stop | Out-Null
      return
    }} catch {{ }}
    try {{
      Set-NetAdapterAdvancedProperty -Name $adapter.Name -RegistryKeyword $keyword -RegistryValue $v -NoRestart -ErrorAction Stop | Out-Null
      return
    }} catch {{ }}
  }}
}}

Set-ByKeyword '*EEE'                        @('0', 'Off', 'Disabled')
Set-ByKeyword 'EEE'                         @('0', 'Off', 'Disabled')
Set-ByKeyword '*InterruptModeration'        @('0', 'Off', 'Disabled')
Set-ByKeyword '*FlowControl'                @('0', 'Disabled', 'Off')
Set-ByKeyword '*RSS'                        @('1', 'Enabled', 'On')
Set-ByKeyword '*LsoV2IPv4'                  @('0', 'Disabled', 'Off')
Set-ByKeyword '*LsoV2IPv6'                  @('0', 'Disabled', 'Off')
Set-ByKeyword '*IPChecksumOffloadIPv4'      @('3', 'Rx & Tx Enabled', 'Rx/Tx Enabled')
Set-ByKeyword '*TCPChecksumOffloadIPv4'     @('3', 'Rx & Tx Enabled', 'Rx/Tx Enabled')
Set-ByKeyword '*UDPChecksumOffloadIPv4'     @('3', 'Rx & Tx Enabled', 'Rx/Tx Enabled')
Set-ByKeyword '*WakeOnMagicPacket'          @('0', 'Disabled', 'Off')
Set-ByKeyword '*WakeOnPattern'              @('0', 'Disabled', 'Off')
Set-ByKeyword '*ReceiveBuffers'             @('2048')
Set-ByKeyword '*TransmitBuffers'            @('2048')
Set-ByKeyword 'ITR'                         @('0', 'Off', 'Disabled', 'Lowest')
Set-ByKeyword '*PriorityVLANTag'            @('0', 'Disabled', 'Off')

$pmOk = $false
try {{
  Set-NetAdapterPowerManagement -Name $adapter.Name `
    -AllowComputerToTurnOffDevice Disabled `
    -WakeOnMagicPacket Disabled `
    -WakeOnPattern Disabled `
    -DeviceSleepOnDisconnect Disabled `
    -ErrorAction Stop | Out-Null
  $pmOk = $true
}} catch {{ }}

if (-not $pmOk) {{
  $guid = $adapter.InterfaceGuid
  $classRoot = 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{{4D36E972-E325-11CE-BFC1-08002BE10318}}'
  Get-ChildItem $classRoot -ErrorAction SilentlyContinue | ForEach-Object {{
    $netCfg = (Get-ItemProperty $_.PSPath -Name 'NetCfgInstanceId' -ErrorAction SilentlyContinue).NetCfgInstanceId
    if ($netCfg -eq $guid) {{
      Set-ItemProperty $_.PSPath -Name 'PnPCapabilities' -Value 0x118 -Type DWord -ErrorAction SilentlyContinue
    }}
  }}
}}
"""
    _run_powershell(ps)


def ensure_npcap_ethernet_filter(iface_name: str = '') -> None:
    """Enable Npcap's ethernet LWF on the live Up NIC (not Wi-Fi Direct).

    Npcap often leaves ``INSECURE_NPCAP`` off on USB Wi-Fi and only enables
    ``INSECURE_NPCAP_WIFI``. Scapy then has no ``\\Device\\NPF_{GUID}`` to
    sniff/inject, so Kill and Quick Check fail with Interface not found.
    """
    if not sys.platform.startswith('win') or not _is_admin():
        return
    safe = _safe_adapter_name(iface_name)
    if not safe:
        return
    ps = f"""
$ErrorActionPreference = 'SilentlyContinue'
$a = Get-NetAdapter -Name '{safe}' -ErrorAction SilentlyContinue
if (-not $a -or $a.Status -ne 'Up') {{ return }}
$desc = [string]$a.InterfaceDescription
if ($a.Name -match 'Local Area Connection' -or $desc -match 'Direct|Hosted|Hotspot') {{ return }}
$b = Get-NetAdapterBinding -Name $a.Name -ComponentID 'INSECURE_NPCAP' -ErrorAction SilentlyContinue
if ($b -and -not $b.Enabled) {{
  Enable-NetAdapterBinding -Name $a.Name -ComponentID 'INSECURE_NPCAP' | Out-Null
}}
"""
    _run_powershell(ps)


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
    try:
        ensure_npcap_ethernet_filter(active)
    except Exception:
        pass

    try:
        from tools.clumsy_inline import ics_forwarding_must_stay_on

        if ics_forwarding_must_stay_on():
            # Hotspot / ICS is live (Clumsy checkbox may be off). Do not flip
            # forwarding, NIC power, or other bindings — that drops the PC uplink.
            return
    except Exception:
        pass

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
  $desc = [string]$a.InterfaceDescription
  $isWifi = ($a.Name -match 'Wi-?Fi|Wireless' -or $desc -match 'Wi-?Fi|Wireless|802\.11|Direct|Hosted|Hotspot')
  $w = Get-NetAdapterBinding -Name $a.Name -ComponentID 'Win10Pcap' -ErrorAction SilentlyContinue
  if ($w -and $w.Enabled) {{
    Disable-NetAdapterBinding -Name $a.Name -ComponentID 'Win10Pcap' | Out-Null
  }}
  if ($isWifi) {{ continue }}
  Set-NetAdapterPowerManagement -Name $a.Name `
    -AllowComputerToTurnOffDevice Disabled `
    -WakeOnMagicPacket Disabled `
    -WakeOnPattern Disabled `
    -DeviceSleepOnDisconnect Disabled `
    -ErrorAction SilentlyContinue | Out-Null
}}
"""
    _run_powershell(ps)
    skip_aspm = False
    try:
        from tools.clumsy_inline import ics_forwarding_must_stay_on

        skip_aspm = bool(ics_forwarding_must_stay_on())
    except Exception:
        skip_aspm = False
    if not skip_aspm:
        _disable_pcie_aspm()
    if active:
        _apply_intel_ethernet_low_latency(active)
    ensure_home_lan_mitm_forwarding_off()


def schedule_windows_capture_maintenance(
    *,
    iface_name: str = '',
    force: bool = False,
    prewarm=None,
) -> None:
    """Background maintenance + optional Killer.prewarm_l2_socket callback."""

    def _work() -> None:
        try:
            from tools.clumsy_inline import ics_forwarding_must_stay_on

            if ics_forwarding_must_stay_on():
                return
        except Exception:
            pass
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
