from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any, Dict, Tuple

from constants import DOCUMENTS_PATH

_STATE_PATH = os.path.join(DOCUMENTS_PATH, 'clumsy_ics_state.json')
_MARKER = 'ZUBCUT_JSON:'


def _parse_marker_json(text: str) -> Dict[str, Any]:
    """
    Extract the last ZUBCUT_JSON payload from PowerShell output.

    Windows PowerShell may split ``Write-Output 'MARKER' + ($json)`` into two
    lines (marker only, then JSON), which would otherwise make json.loads fail
    and treat a successful ICS script as failure.
    """
    if not text:
        return {}
    lines = [ln.lstrip('\ufeff') for ln in text.splitlines()]
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if not line.startswith(_MARKER):
            continue
        tail = line[len(_MARKER) :].strip()
        if tail:
            try:
                return json.loads(tail)
            except Exception:
                pass
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if nxt:
                try:
                    return json.loads(nxt)
                except Exception:
                    pass
        idx = text.rfind(_MARKER)
        if idx >= 0:
            blob = text[idx + len(_MARKER) :].strip()
            try:
                return json.loads(blob)
            except Exception:
                pass
        break
    return {}


def clumsy_ics_state_path() -> str:
    return _STATE_PATH


def read_clumsy_ics_state() -> Dict[str, Any]:
    try:
        with open(_STATE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def normalize_clumsy_topology(topology: str | None) -> str:
    t = (topology or '').strip().lower()
    if t in ('hotspot', 'wifi', 'wi-fi', 'wlan', 'mobile'):
        return 'hotspot'
    return 'ethernet'


def read_clumsy_topology() -> str:
    try:
        from tools.utils_gui import get_settings

        return normalize_clumsy_topology(str(get_settings('clumsy_topology') or 'hotspot'))
    except Exception:
        return 'hotspot'


def _clumsy_error_has_hotspot_hints(detail: str) -> bool:
    low = (detail or '').lower()
    return 'connect the ps5' in low and 'mobile hotspot' in low


def format_clumsy_ics_error(detail: str, *, topology: str | None = None) -> str:
    """User-facing hints for common ICS / HNetCfg failures (incl. HRESULT 0x80040201)."""
    topo = normalize_clumsy_topology(topology) if topology else read_clumsy_topology()
    d = (detail or '').strip()
    lines = [d] if d else []
    low = d.lower()
    if topo == 'hotspot' and not _clumsy_error_has_hotspot_hints(d):
        lines.extend(
            [
                '',
                'For PS5 → PC Mobile Hotspot → router:',
                '• Turn ON Mobile hotspot (Settings → Network → Mobile hotspot)',
                '• Connect the PS5 to your PC hotspot Wi‑Fi (not the router Wi‑Fi)',
                '• In ZubCut Settings, set Console connects via → PC Mobile Hotspot',
                '• Run ZubCut as Administrator, then enable Clumsy mode again',
            ]
        )
        if 'repair hotspot' not in low and 'ethernet' not in low:
            lines.extend(
                [
                    '',
                    'Try Settings → Repair hotspot / sharing (ZubCut toggles hotspot to apply sharing).',
                    'Or use Console connects via → Ethernet (PS5 cable to PC LAN port).',
                ]
            )
    if '0x80040201' in low or 'abonnenten' in low or 'subscribers' in low:
        if topo == 'ethernet':
            lines.extend(
                [
                    '',
                    'This Windows sharing error is often fixed by:',
                    '• Turn off Mobile hotspot (Settings → Network → Mobile hotspot)',
                    '• Network connections → your internet adapter → Properties → Sharing: '
                    'uncheck sharing, Apply, then try Clumsy mode again',
                    '• Set both Ethernet adapters to Private network, then retry',
                ]
            )
    if 'administrator' not in low and 'admin' not in low:
        lines.extend(['', '• Run ZubCut as Administrator (right-click → Run as administrator)'])
    return '\n'.join(lines)


def _windows_is_admin() -> bool:
    if os.name != 'nt':
        return True
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# Never set WlanSvc to Manual or force-stop it (breaks Wi-Fi network list on Windows).
_PS_ENSURE_WLAN_HEALTHY = """
function Ensure-WlanAutoConfigHealthy {
  $fixed = $false
  try {
    $wl = Get-Service -Name WlanSvc -ErrorAction Stop
    if ($wl.StartType -notin @('Automatic', 'AutomaticDelayedStart')) {
      Set-Service -Name WlanSvc -StartupType Automatic -ErrorAction SilentlyContinue
      $fixed = $true
    }
    if ($wl.Status -ne 'Running') {
      Start-Service -Name WlanSvc -ErrorAction SilentlyContinue
      $fixed = $true
    }
  } catch {
    try { Set-Service -Name WlanSvc -StartupType Automatic -ErrorAction SilentlyContinue } catch {}
    try { Start-Service -Name WlanSvc -ErrorAction SilentlyContinue } catch {}
    $fixed = $true
  }
  return $fixed
}
"""

# Hotspot: DHCP alone is not enough — PS5 needs ICS (Wi‑Fi public → Wi‑Fi Direct private).
_PS_HOTSPOT_HELPERS = """
function NormGuidHotspot([object]$g) {
  if ($null -eq $g) { return '' }
  return ($g.ToString().Trim('{','}').ToLowerInvariant())
}
function SharingTypeNumHotspot($cfg) {
  if ($null -eq $cfg) { return -1 }
  try {
    $t = $cfg.SharingConnectionType
    if ($null -eq $t) { return -1 }
    try { return [System.Convert]::ToInt32($t) } catch { return [int]$t }
  } catch { return -1 }
}
function Test-MobileHotspotGateway {
  return [bool](Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1)
}
function Get-HotspotAdapterPair {
  $gw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1
  if (-not $gw) { return @{ Up=$null; Down=$null } }
  $down = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -and $_.Status -eq 'Up'
  } | Select-Object -First 1
  if (-not $down) {
    $down = Get-NetAdapter -InterfaceIndex $gw.InterfaceIndex -ErrorAction SilentlyContinue
  }
  $up = $null
  $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric, InterfaceMetric
  foreach ($rt in @($routes)) {
    $cand = Get-NetAdapter -InterfaceIndex $rt.InterfaceIndex -ErrorAction SilentlyContinue
    if ($cand -and $cand.Status -eq 'Up' -and (-not $down -or $cand.ifIndex -ne $down.ifIndex)) {
      if ($cand.InterfaceDescription -notmatch 'Direct|Bluetooth|Virtual|Hyper-V|Loopback') {
        $up = $cand
        break
      }
    }
  }
  if (-not $up) {
    $up = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
      $_.Status -eq 'Up' -and ($_.Name -eq 'Wi-Fi' -or $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi')
      $_.InterfaceDescription -notmatch 'Direct|Virtual|Bluetooth'
    } | Select-Object -First 1
  }
  return @{ Up=$up; Down=$down }
}
function Test-HotspotDhcp67 {
  return [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue)
}
function Test-HotspotIcsActive {
  $pair = Get-HotspotAdapterPair
  if ($null -eq $pair.Up -or $null -eq $pair.Down) { return $false }
  $upG = NormGuidHotspot $pair.Up.InterfaceGuid
  $dnG = NormGuidHotspot $pair.Down.InterfaceGuid
  $share = New-Object -ComObject HNetCfg.HNetShare
  $upPublic = $false
  $dnPrivate = $false
  foreach ($conn in @($share.EnumEveryConnection())) {
    try {
      $props = $share.NetConnectionProps($conn)
      $g = NormGuidHotspot $props.Guid
      $cfg = $share.INetSharingConfigurationForINetConnection($conn)
      if (-not $cfg.SharingEnabled) { continue }
      $st = SharingTypeNumHotspot $cfg
      if ($g -eq $upG -and $st -eq 0) { $upPublic = $true }
      if ($g -eq $dnG -and $st -eq 1) { $dnPrivate = $true }
    } catch {}
  }
  return ($upPublic -and $dnPrivate)
}
function Get-HotspotAdapterPairForIcs {
  $up = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.InterfaceDescription -notmatch 'Direct|Bluetooth|Virtual|Hyper-V|Loopback'
    -and ($_.Name -eq 'Wi-Fi' -or $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi')
  } | Sort-Object @{ Expression = { if ($_.Status -eq 'Up') { 0 } else { 1 } } }, InterfaceMetric | Select-Object -First 1
  $down = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection'
  } | Sort-Object @{ Expression = { if ($_.Status -eq 'Up') { 0 } else { 1 } } } | Select-Object -First 1
  return @{ Up=$up; Down=$down }
}
function Apply-HotspotIcsCore($pair) {
  if ($null -eq $pair.Up -or $null -eq $pair.Down) { return $false }
  $share = New-Object -ComObject HNetCfg.HNetShare
  $connMap = @{}
  foreach ($conn in @($share.EnumEveryConnection())) {
    try {
      $p = $share.NetConnectionProps($conn)
      $g = NormGuidHotspot $p.Guid
      $connMap[$g] = $share.INetSharingConfigurationForINetConnection($conn)
    } catch {}
  }
  $upG = NormGuidHotspot $pair.Up.InterfaceGuid
  $dnG = NormGuidHotspot $pair.Down.InterfaceGuid
  if (-not $connMap.ContainsKey($upG)) {
    $wantUp = ($pair.Up.Name -as [string]).Trim().ToLowerInvariant()
    foreach ($conn in @($share.EnumEveryConnection())) {
      try {
        $p = $share.NetConnectionProps($conn)
        $g = NormGuidHotspot $p.Guid
        if (($p.Name -as [string]).Trim().ToLowerInvariant() -eq $wantUp) { $upG = $g; break }
      } catch {}
    }
  }
  if (-not $connMap.ContainsKey($dnG)) {
    $wantDn = ($pair.Down.Name -as [string]).Trim().ToLowerInvariant()
    foreach ($conn in @($share.EnumEveryConnection())) {
      try {
        $p = $share.NetConnectionProps($conn)
        $g = NormGuidHotspot $p.Guid
        if (($p.Name -as [string]).Trim().ToLowerInvariant() -eq $wantDn) { $dnG = $g; break }
      } catch {}
    }
  }
  if (-not $connMap.ContainsKey($upG) -or -not $connMap.ContainsKey($dnG)) { return $false }
  foreach ($k in $connMap.Keys) {
    try { if ($connMap[$k].SharingEnabled) { $connMap[$k].DisableSharing() } } catch {}
  }
  Start-Sleep -Milliseconds 400
  $ok = $false
  try {
    $connMap[$upG].EnableSharing(0)
    $connMap[$dnG].EnableSharing(1)
    $ok = $true
  } catch {}
  if (-not $ok) {
    foreach ($k in $connMap.Keys) {
      try { if ($connMap[$k].SharingEnabled) { $connMap[$k].DisableSharing() } } catch {}
    }
    Start-Sleep -Milliseconds 400
    try {
      $connMap[$dnG].EnableSharing(1)
      $connMap[$upG].EnableSharing(0)
      $ok = $true
    } catch {}
  }
  Start-Sleep -Seconds 2
  return (Test-HotspotIcsActive)
}
function Apply-HotspotIcs {
  return (Apply-HotspotIcsCore (Get-HotspotAdapterPair))
}
function Stop-MobileHotspotIfOn {
  $mgr = Get-TetheringManager
  if ($null -eq $mgr) { return $false }
  if ($mgr.TetheringOperationalState.ToString() -ne 'On') { return $true }
  try {
    $op = $mgr.StopTetheringAsync()
    if (-not (Wait-TetheringAsync $op 'StopTethering')) { return $false }
    Start-Sleep -Seconds 3
    return $true
  } catch {
    return $false
  }
}
function Apply-HotspotIcsWithTetheringToggle {
  $wasOn = Test-TetheringOn
  if ($wasOn) {
    if (-not (Stop-MobileHotspotIfOn)) { return $false }
    Start-Sleep -Seconds 2
  }
  $pair = Get-HotspotAdapterPairForIcs
  Apply-HotspotIcsCore $pair | Out-Null
  Ensure-MobileHotspotOn | Out-Null
  Start-Sleep -Seconds 8
  return (Test-HotspotIcsActive)
}
function Apply-HotspotIcsAutomated {
  if (Test-HotspotIcsActive) { return $true }
  if (Apply-HotspotIcs) { return $true }
  return (Apply-HotspotIcsWithTetheringToggle)
}
function Wait-TetheringAsync($op, [string]$label) {
  $deadline = (Get-Date).AddSeconds(25)
  while ($op.Status -eq 'Started') {
    if ((Get-Date) -gt $deadline) { return $false }
    Start-Sleep -Milliseconds 250
  }
  return ($op.Status -ne 'Error')
}
function Get-TetheringManager {
  try {
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if (-not $profile) { return $null }
    return [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
  } catch {
    return $null
  }
}
function Test-TetheringOn {
  $mgr = Get-TetheringManager
  if ($null -eq $mgr) { return $false }
  return ($mgr.TetheringOperationalState.ToString() -eq 'On')
}
function Ensure-MobileHotspotOn {
  $mgr = Get-TetheringManager
  if ($null -eq $mgr) { return $false }
  if ($mgr.TetheringOperationalState.ToString() -eq 'On') { return $true }
  try {
    $op = $mgr.StartTetheringAsync()
    if (-not (Wait-TetheringAsync $op 'StartTethering')) { return $false }
    Start-Sleep -Seconds 6
    return ((Test-TetheringOn) -and (Test-MobileHotspotGateway))
  } catch {
    return $false
  }
}
function Restart-SharedAccessSafe([bool]$hotspotWasOn) {
  try {
    $sa = Get-Service -Name SharedAccess -ErrorAction Stop
    if ($sa.Status -ne 'Running') {
      Start-Service -Name SharedAccess -ErrorAction SilentlyContinue
      return
    }
    if ($hotspotWasOn) {
      return
    }
    Restart-Service -Name SharedAccess -Force -ErrorAction SilentlyContinue
  } catch {}
}
"""


def _run_powershell(script_body: str) -> Tuple[bool, Dict[str, Any], str]:
    fd, path = tempfile.mkstemp(prefix='zubcut_clumsy_', suffix='.ps1')
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(script_body)
        system_root = os.environ.get('SystemRoot', r'C:\Windows')
        explicit_ps = os.path.join(system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        script_args = [
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            path,
        ]
        cmd_candidates = []
        if os.path.isfile(explicit_ps):
            cmd_candidates.append([explicit_ps] + script_args)
        # Fallback to PATH-based invocations for robustness.
        cmd_candidates.extend([
            ['powershell'] + script_args,
            ['powershell.exe'] + script_args,
            ['pwsh'] + script_args,
            ['pwsh.exe'] + script_args,
        ])

        proc = None
        last_exc: Exception | None = None
        # Avoid flashing a visible PowerShell console when toggling ICS from the GUI.
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        for cmd in cmd_candidates:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    creationflags=creationflags,
                )
                break
            except FileNotFoundError as e:
                last_exc = e
        if proc is None:
            out = str(last_exc or 'PowerShell executable not found.')
            payload = {'ok': False, 'error': out}
            return False, payload, out

        out = (proc.stdout or '') + '\n' + (proc.stderr or '')
        payload = _parse_marker_json(out)
        ok = bool(proc.returncode == 0 and payload.get('ok') is True)
        if not payload:
            payload = {'ok': ok, 'error': out.strip()}
        return ok, payload, out
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def prepare_pc_mobile_hotspot() -> Tuple[bool, str]:
    """
    Best-effort automation for PC Mobile Hotspot → console (DHCP, firewall, ICS).

    Fully automatic on most PCs: tries ICS while hotspot is on, then briefly toggles
    hotspot off/on via Windows APIs to apply sharing (same as manual Sharing tab).
    """
    if os.name != 'nt':
        return True, 'Non-Windows platform; skipping hotspot prep.'
    if not _windows_is_admin():
        return False, 'Run ZubCut as Administrator to prepare Mobile Hotspot.'

    script = f"""
$ErrorActionPreference = 'Continue'
function JsonOut([hashtable]$o) {{
  $json = $o | ConvertTo-Json -Compress -Depth 8
  Write-Output ('{_MARKER}' + $json)
}}
{_PS_ENSURE_WLAN_HEALTHY}
{_PS_HOTSPOT_HELPERS}
Ensure-WlanAutoConfigHealthy | Out-Null

Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object {{ $_.IPAddress -eq '192.168.137.1' }} | ForEach-Object {{
  $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
  if ($a -and $a.InterfaceDescription -notmatch 'Direct|Hosted' -and $a.Name -notmatch 'Local Area Connection') {{
    Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -EA SilentlyContinue
  }}
}}

foreach ($r in @(
  @{{N='ZubCut-DHCP-In';D='in';P=67}}, @{{N='ZubCut-DHCP-Out';D='out';P=67}},
  @{{N='ZubCut-DHCPClient-In';D='in';P=68}}, @{{N='ZubCut-DHCPClient-Out';D='out';P=68}}
)) {{
  netsh advfirewall firewall delete rule name="$($r.N)" 2>$null | Out-Null
  netsh advfirewall firewall add rule name="$($r.N)" dir=$($r.D) action=allow protocol=UDP localport=$($r.P) enable=yes | Out-Null
}}
netsh advfirewall firewall delete rule name="ZubCut-Hotspot-Subnet-In" 2>$null | Out-Null
netsh advfirewall firewall add rule name="ZubCut-Hotspot-Subnet-In" dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name="ZubCut-Hotspot-Subnet-Out" dir=out action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null

$saParams = 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\SharedAccess\\Parameters'
foreach ($pair in @('ScopeAddress','ScopeAddressBackup','StandaloneDhcpAddress')) {{
  try {{ Set-ItemProperty -Path $saParams -Name $pair -Value '192.168.137.1' -Type String -Force -EA SilentlyContinue }} catch {{}}
}}
try {{
  Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters' -Name 'IPEnableRouter' -Value 1 -Type DWord -Force -EA SilentlyContinue
}} catch {{}}

foreach ($svc in @('SharedAccess','icssvc','WlanSvc','Dhcp')) {{
  try {{ Start-Service $svc -ErrorAction SilentlyContinue }} catch {{}}
}}

$hotspotWasOn = (Test-MobileHotspotGateway) -or (Test-TetheringOn)
$gw = Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object {{ $_.IPAddress -eq '192.168.137.1' }} | Select-Object -First 1
if (-not $gw) {{
  if ($hotspotWasOn) {{
    Ensure-MobileHotspotOn | Out-Null
    Start-Sleep -Seconds 5
    $gw = Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object {{ $_.IPAddress -eq '192.168.137.1' }} | Select-Object -First 1
  }}
  if (-not $gw) {{
    JsonOut @{{ ok=$false; dhcp67=$false; needs_manual_sharing=$false; error='Turn ON Mobile Hotspot in Windows Settings first.' }}
    exit 1
  }}
}}

$up = Get-NetAdapter -EA SilentlyContinue | Where-Object {{ $_.Status -eq 'Up' -and $_.InterfaceDescription -notmatch 'Direct|Virtual|Bluetooth' -and ($_.Name -eq 'Wi-Fi' -or $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi') }} | Select-Object -First 1
$down = Get-NetAdapter -EA SilentlyContinue | Where-Object {{ $_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -and $_.Status -eq 'Up' }} | Select-Object -First 1
if (-not $down) {{
  $down = Get-NetAdapter -InterfaceIndex $gw.InterfaceIndex -EA SilentlyContinue
}}

$dhcp67 = Test-HotspotDhcp67
$icsOk = Test-HotspotIcsActive
if ($dhcp67 -and $icsOk) {{
  JsonOut @{{ ok=$true; dhcp67=$true; ics_ok=$true; needs_manual_sharing=$false; message='Mobile Hotspot DHCP and internet sharing (ICS) are active.' }}
  exit 0
}}
if ($dhcp67 -and -not $icsOk) {{
  if (Apply-HotspotIcsAutomated) {{
    JsonOut @{{ ok=$true; dhcp67=$true; ics_ok=$true; needs_manual_sharing=$false; message='Restored internet sharing (ICS) for Mobile Hotspot.' }}
    exit 0
  }}
}}

Apply-HotspotIcsAutomated | Out-Null
Restart-SharedAccessSafe $hotspotWasOn
if ($hotspotWasOn -and -not (Test-TetheringOn)) {{ Ensure-MobileHotspotOn | Out-Null }}
Start-Sleep -Seconds 5
$dhcp67 = Test-HotspotDhcp67
$icsOk = Test-HotspotIcsActive
if ($dhcp67 -and $icsOk) {{
  JsonOut @{{ ok=$true; dhcp67=$true; ics_ok=$true; needs_manual_sharing=$false; message='Mobile Hotspot is ready for your console (Wi-Fi sharing enabled automatically).' }}
  exit 0
}}
if ($dhcp67 -and -not $icsOk) {{
  JsonOut @{{
    ok=$false
    dhcp67=$true
    ics_ok=$false
    needs_manual_sharing=$true
    error='Hotspot is on but automatic Wi-Fi sharing failed on this adapter. Try Settings -> Repair hotspot / sharing, or use Console connects via -> Ethernet (PS5 cable to PC LAN port).'
  }}
  exit 1
}}

JsonOut @{{
  ok=$false
  dhcp67=$false
  needs_manual_sharing=$true
  error='Could not enable Mobile Hotspot sharing automatically. Turn hotspot ON in Windows Settings, then use Repair hotspot / sharing in ZubCut Settings, or switch to Ethernet topology.'
}}
exit 1
"""
    ok, payload, raw = _run_powershell(script)
    if ok and payload.get('dhcp67'):
        return True, str(payload.get('message') or 'Mobile Hotspot ready.')
    if payload.get('needs_manual_sharing'):
        return False, str(
            payload.get('error')
            or (
                'Automatic hotspot sharing could not be enabled. '
                'Try Repair hotspot / sharing in Settings, or use Ethernet (PS5 → LAN port) in Settings.'
            )
        )
    msg = str(payload.get('error') or '').strip() or raw.strip() or 'Hotspot preparation failed.'
    return False, msg


def ensure_clumsy_ics_enabled(topology: str | None = None) -> Tuple[bool, str]:
    if os.name != 'nt':
        return True, 'Non-Windows platform; skipping ICS automation.'
    if not _windows_is_admin():
        return (
            False,
            'ZubCut must run as Administrator to enable Internet Connection Sharing. '
            'Close ZubCut, right-click the shortcut, choose Run as administrator, then try again.',
        )
    topo = normalize_clumsy_topology(topology) if topology else read_clumsy_topology()
    if topo == 'hotspot':
        prep_ok, prep_detail = prepare_pc_mobile_hotspot()
        if not prep_ok:
            return False, prep_detail
    os.makedirs(DOCUMENTS_PATH, exist_ok=True)
    state_path = _STATE_PATH.replace('\\', '\\\\')
    script = f"""
$ErrorActionPreference = 'Stop'
$ZubcutTopology = '{topo}'
function NormGuid([object]$g) {{
  if ($null -eq $g) {{ return '' }}
  return ($g.ToString().Trim('{{','}}').ToLowerInvariant())
}}
function IsVirtualLike([string]$name, [string]$desc) {{
  $all = (($name + ' ' + $desc) -as [string]).ToLowerInvariant()
  if ($ZubcutTopology -eq 'hotspot' -and ($all -match 'wi-fi direct|hosted network|mobile hotspot|local area connection\\*')) {{
    return $false
  }}
  return ($all -match 'hyper-v|vethernet|virtual|bluetooth|loopback|tap|vpn|wireguard|vmware|npcap loopback')
}}
function IsHotspotLike([string]$name, [string]$desc) {{
  $all = (($name + ' ' + $desc) -as [string]).ToLowerInvariant()
  return ($all -match 'wi-fi direct|hosted network|mobile hotspot|local area connection\\*|microsoft wi-fi direct')
}}
function LikelyHotspotDownstream($a) {{
  if (IsHotspotLike $a.Name $a.InterfaceDescription) {{ return $true }}
  try {{
    $ips = @(Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue)
    foreach ($ip in $ips) {{
      if ($ip.IPAddress -and $ip.IPAddress -notlike '169.254.*' -and $ip.IPAddress -match '^192\\.168\\.\\d+\\.\\d+$') {{
        $last = [int]($ip.IPAddress.Split('.')[-1])
        if ($last -eq 1) {{ return $true }}
      }}
    }}
  }} catch {{}}
  return $false
}}
function JsonOut([hashtable]$o) {{
  $json = $o | ConvertTo-Json -Compress -Depth 8
  Write-Output ('{_MARKER}' + $json)
}}
function SharingTypeNum($cfg) {{
  if ($null -eq $cfg) {{ return -1 }}
  try {{
    $t = $cfg.SharingConnectionType
    if ($null -eq $t) {{ return -1 }}
    try {{ return [System.Convert]::ToInt32($t) }} catch {{
      try {{ return [int]$t }} catch {{ return -1 }}
    }}
  }} catch {{
    return -1
  }}
}}
function SharingEnabledSafe($cfg) {{
  if ($null -eq $cfg) {{ return $false }}
  try {{
    $v = $cfg.SharingEnabled
    if ($null -eq $v) {{ return $false }}
    if ($v -is [bool]) {{ return $v }}
    try {{ return [bool][int]$v }} catch {{ return $false }}
  }} catch {{
    return $false
  }}
}}
function DisableSharingSafe([object]$cfg) {{
  if ($null -eq $cfg) {{ return }}
  if (-not (SharingEnabledSafe $cfg)) {{ return }}
  for ($i = 0; $i -lt 3; $i++) {{
    try {{ $cfg.DisableSharing(); return }} catch {{ Start-Sleep -Milliseconds 600 }}
  }}
}}
function Invoke-EnableSharingOnce([object]$cfg, [int]$sharingKind) {{
  if ($null -eq $cfg) {{ throw 'EnableSharingSafe: null configuration object.' }}
  try {{
    $mi = $cfg.GetType().GetMethod('EnableSharing')
    if ($null -ne $mi) {{
      $parms = $mi.GetParameters()
      if ($parms.Length -eq 1) {{
        $enumType = $parms[0].ParameterType
        if ($enumType.IsEnum) {{
          $arg = [System.Enum]::ToObject($enumType, [int32]$sharingKind)
          $mi.Invoke($cfg, @($arg))
          return
        }}
      }}
    }}
  }} catch {{ }}
  $lastErr = $null
  try {{ $cfg.EnableSharing([int32]$sharingKind); return }} catch {{ $lastErr = $_ }}
  try {{ $cfg.EnableSharing([uint32]$sharingKind); return }} catch {{ $lastErr = $_ }}
  try {{ $cfg.EnableSharing([int16]$sharingKind); return }} catch {{ $lastErr = $_ }}
  try {{ $cfg.EnableSharing($sharingKind); return }} catch {{ $lastErr = $_ }}
  if ($null -ne $lastErr) {{ throw $lastErr.Exception }}
  throw 'EnableSharing failed (no matching invocation).'
}}
function EnableSharingSafe([object]$cfg, [int]$sharingKind) {{
  $lastErr = $null
  for ($try = 0; $try -lt 4; $try++) {{
    try {{
      Invoke-EnableSharingOnce $cfg $sharingKind
      return
    }} catch {{
      $lastErr = $_
      try {{ Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue }} catch {{}}
      Start-Sleep -Seconds 2
    }}
  }}
  if ($null -ne $lastErr) {{ throw $lastErr.Exception }}
  throw 'EnableSharing failed after retries.'
}}
try {{
  # ICS / sharing: start related services (best-effort; do not change startup types).
  foreach ($svc in @('RemoteAccess', 'SharedAccess', 'NlaSvc')) {{
    try {{ Start-Service -Name $svc -ErrorAction SilentlyContinue }} catch {{}}
  }}

  # Include USB/LAN adapters; hotspot mode also allows Wi-Fi Direct / Mobile Hotspot NICs.
  $allAdapters = Get-NetAdapter -ErrorAction Stop | Where-Object {{
    if ($_.Status -eq 'Disabled') {{ return $false }}
    if ($ZubcutTopology -eq 'hotspot' -and (LikelyHotspotDownstream $_)) {{ return $true }}
    if (IsVirtualLike $_.Name $_.InterfaceDescription) {{ return $false }}
    $virtBad = $false
    try {{ if ($null -ne $_.Virtual -and $_.Virtual -eq $true) {{ $virtBad = $true }} }} catch {{ }}
    if ($virtBad) {{ return $false }}
    if ($_.HardwareInterface -eq $true) {{ return $true }}
    $d = ($_.Name + ' ' + $_.InterfaceDescription)
    if ($d -match 'USB|Ethernet|Gigabit|GbE|LAN|RNDIS|ASIX|AX88179|NDIS|Thunderbolt|Wi-Fi|WiFi|Wireless') {{ return $true }}
    return $false
  }}
  if (-not $allAdapters) {{
    if ($ZubcutTopology -eq 'hotspot') {{
      throw 'No hotspot adapter found. Turn on Mobile Hotspot, connect the PS5 to that Wi-Fi, then try again.'
    }}
    throw 'No usable adapters found for Clumsy sharing.'
  }}

  function LikelyEthernet($a) {{
    $d = ($a.Name + ' ' + $a.InterfaceDescription)
    if ($d -match 'Ethernet|Gigabit|GbE|^LAN|USB.*Ethernet|RNDIS|PCIe.*Family|ASIX|AX88179') {{ return $true }}
    try {{ if ($a.MediaType -eq '802.3') {{ return $true }} }} catch {{}}
    return $false
  }}

  if ($ZubcutTopology -eq 'hotspot') {{
    # Downstream = PC Mobile Hotspot / Wi-Fi Direct (console-facing).
    $downCandidates = $allAdapters | Where-Object {{
      (LikelyHotspotDownstream $_) -and $_.Status -eq 'Up'
    }} | Sort-Object InterfaceMetric, ifIndex
    if (-not $downCandidates) {{
      $downCandidates = $allAdapters | Where-Object {{ LikelyHotspotDownstream $_ }} | Sort-Object InterfaceMetric, ifIndex
    }}
  }} else {{
    # Downstream = console Ethernet port.
    $downCandidates = $allAdapters | Where-Object {{
      (LikelyEthernet $_) -and $_.Status -eq 'Up'
    }} | Sort-Object InterfaceMetric, ifIndex
    if (-not $downCandidates) {{
      $downCandidates = $allAdapters | Where-Object {{
        $_.Name -match 'Ethernet' -or $_.InterfaceDescription -match 'Ethernet'
      }} | Sort-Object InterfaceMetric, ifIndex
    }}
  }}
  if (-not $downCandidates) {{
    $downCandidates = $allAdapters | Where-Object {{ $_.Status -eq 'Up' }} | Sort-Object InterfaceMetric, ifIndex
  }}
  if (-not $downCandidates) {{
    $downCandidates = $allAdapters | Sort-Object InterfaceMetric, ifIndex
  }}
  $down = $downCandidates | Select-Object -First 1
  if ($null -eq $down) {{
    if ($ZubcutTopology -eq 'hotspot') {{
      throw 'Could not find PC hotspot adapter. Turn on Mobile Hotspot in Windows Settings first.'
    }}
    throw 'Could not choose downstream adapter.'
  }}
  $downGuid = NormGuid($down.InterfaceGuid)

  # Upstream is the internet-facing adapter: default-route owner excluding downstream.
  $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric, InterfaceMetric
  $up = $null
  foreach ($rt in @($routes)) {{
    try {{
      $cand = Get-NetAdapter -InterfaceIndex $rt.InterfaceIndex -ErrorAction Stop
      if ($ZubcutTopology -eq 'hotspot' -and (LikelyHotspotDownstream $cand)) {{ continue }}
      if ($cand -and (NormGuid($cand.InterfaceGuid)) -ne $downGuid -and -not (IsVirtualLike $cand.Name $cand.InterfaceDescription)) {{
        $up = $cand
        break
      }}
    }} catch {{}}
  }}
  if ($null -eq $up) {{
    $up = $allAdapters | Where-Object {{ (NormGuid($_.InterfaceGuid)) -ne $downGuid -and $_.Status -eq 'Up' }} |
      Sort-Object InterfaceMetric, ifIndex | Select-Object -First 1
  }}
  if ($null -eq $up) {{
    $up = $allAdapters | Where-Object {{ (NormGuid($_.InterfaceGuid)) -ne $downGuid }} |
      Sort-Object InterfaceMetric, ifIndex | Select-Object -First 1
  }}
  if ($null -eq $up) {{ throw 'Could not choose upstream adapter.' }}
  $upGuid = NormGuid($up.InterfaceGuid)

  $share = New-Object -ComObject HNetCfg.HNetShare
  $connMap = @{{}}
  $snapshot = @()
  foreach ($conn in @($share.EnumEveryConnection())) {{
    try {{
      $props = $share.NetConnectionProps($conn)
      $guid = NormGuid($props.Guid)
      $cfg = $share.INetSharingConfigurationForINetConnection($conn)
      $connMap[$guid] = @{{ conn=$conn; cfg=$cfg; name=$props.Name }}
      if (SharingEnabledSafe $cfg) {{
        $snapshot += @{{ guid=$guid; type=(SharingTypeNum $cfg); name=$props.Name }}
      }}
    }} catch {{ continue }}
  }}
  function Resolve-ConnGuid([string]$guid, [string]$ifaceName) {{
    if ($connMap.ContainsKey($guid)) {{ return $guid }}
    $want = ($ifaceName -as [string]).Trim().ToLowerInvariant()
    foreach ($k in $connMap.Keys) {{
      $nm = ($connMap[$k].name -as [string]).Trim().ToLowerInvariant()
      if ($nm -and $nm -eq $want) {{ return [string]$k }}
    }}
    return ''
  }}
  $upKey = Resolve-ConnGuid $upGuid $up.Name
  $dnKey = Resolve-ConnGuid $downGuid $down.Name
  if (-not $upKey) {{ throw ('Upstream adapter not found in sharing manager (GUID/name). NetAdapter=' + $up.Name) }}
  if (-not $dnKey) {{ throw ('Downstream adapter not found in sharing manager (GUID/name). NetAdapter=' + $down.Name) }}

  function Write-ClumsyState([object]$up, [object]$down, [array]$snapshot, [string]$msg) {{
    $downIpObj = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $down.ifIndex -ErrorAction SilentlyContinue |
      Where-Object {{ $_.IPAddress -and $_.IPAddress -notlike '169.254.*' }} |
      Sort-Object SkipAsSource | Select-Object -First 1
    $downIp = if ($downIpObj) {{ $downIpObj.IPAddress }} else {{ '' }}
    if (-not $downIp) {{ throw 'Downstream adapter has no IPv4 yet.' }}
    $prefix = ''
    if ($downIp -match '^(\\d+\\.\\d+\\.\\d+)\\.') {{ $prefix = $Matches[1] + '.' }}
    if (-not $prefix) {{ throw 'Could not determine downstream subnet prefix.' }}
    $state = @{{
      enabled_by_zubcut = $true
      topology = $ZubcutTopology
      upstream_guid = (NormGuid $up.InterfaceGuid)
      upstream_name = $up.Name
      downstream_guid = (NormGuid $down.InterfaceGuid)
      downstream_name = $down.Name
      downstream_ipv4 = $downIp
      downstream_prefix = $prefix
      snapshot = $snapshot
      ts = (Get-Date).ToUniversalTime().ToString('o')
    }}
    $state | ConvertTo-Json -Depth 8 | Set-Content -Path "{state_path}" -Encoding UTF8
    JsonOut @{{ ok=$true; message=$msg; state=$state }}
    exit 0
  }}

  if ($ZubcutTopology -eq 'hotspot') {{
    try {{ Set-NetConnectionProfile -InterfaceIndex $up.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    try {{ Set-NetConnectionProfile -InterfaceIndex $down.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    $downIpProbe = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $down.ifIndex -ErrorAction SilentlyContinue |
      Where-Object {{ $_.IPAddress -and $_.IPAddress -notlike '169.254.*' }} |
      Sort-Object SkipAsSource | Select-Object -First 1
    if (-not $downIpProbe -or -not $downIpProbe.IPAddress) {{
      throw ('Mobile Hotspot is not active yet. Turn ON Mobile hotspot in Windows Settings, connect the PS5 to your PC hotspot Wi-Fi (not the router), then enable Clumsy mode again.')
    }}
    $dhcpListen = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
    if ($dhcpListen) {{
      Write-ClumsyState $up $down $snapshot 'PC Mobile Hotspot ready (DHCP active).'
    }}
    # Hotspot UI can be On without DHCP (no UDP 67). Enable ICS Wi-Fi -> hotspot like ethernet mode.
    try {{ Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }} catch {{}}
  }} else {{

    try {{ netsh wlan stop hostednetwork 2>$null | Out-Null }} catch {{}}
    try {{ Set-NetConnectionProfile -InterfaceIndex $up.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    try {{ Set-NetConnectionProfile -InterfaceIndex $down.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    try {{ Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }} catch {{}}
  }}

  function Apply-ICS([bool]$privateFirst) {{
    foreach ($k in $connMap.Keys) {{
      DisableSharingSafe $connMap[$k].cfg
    }}
    Start-Sleep -Milliseconds 400
    if ($privateFirst) {{
      EnableSharingSafe $connMap[$dnKey].cfg 1
      EnableSharingSafe $connMap[$upKey].cfg 0
    }} else {{
      EnableSharingSafe $connMap[$upKey].cfg 0
      EnableSharingSafe $connMap[$dnKey].cfg 1
    }}
  }}
  function Verify-ICS {{
    $sh2 = New-Object -ComObject HNetCfg.HNetShare
    $okUp = $false
    $okDn = $false
    foreach ($conn in @($sh2.EnumEveryConnection())) {{
      try {{
        $props = $sh2.NetConnectionProps($conn)
        $g = NormGuid($props.Guid)
        $cfg = $sh2.INetSharingConfigurationForINetConnection($conn)
        if (-not (SharingEnabledSafe $cfg)) {{ continue }}
        $st = SharingTypeNum $cfg
        if ($g -eq $upKey -and $st -eq 0) {{ $okUp = $true }}
        if ($g -eq $dnKey -and $st -eq 1) {{ $okDn = $true }}
      }} catch {{ continue }}
    }}
    return ($okUp -and $okDn)
  }}

  if (Verify-ICS) {{
    Write-ClumsyState $up $down $snapshot 'ICS sharing already active.'
  }}

  try {{
    try {{ Set-NetConnectionProfile -InterfaceIndex $down.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    try {{ Enable-NetAdapter -Name $down.Name -Confirm:$false -ErrorAction SilentlyContinue }} catch {{}}
    $applied = $false
    foreach ($privFirst in @($false, $true)) {{
      try {{
        Apply-ICS $privFirst
        Start-Sleep -Seconds 2
        if (Verify-ICS) {{ $applied = $true; break }}
      }} catch {{
        foreach ($k in $connMap.Keys) {{ DisableSharingSafe $connMap[$k].cfg }}
        foreach ($row in @($snapshot)) {{
          $g = NormGuid($row.guid)
          if (-not $connMap.ContainsKey($g)) {{ continue }}
          try {{ $kind = [System.Convert]::ToInt32($row.type) }} catch {{ continue }}
          if ($kind -ne 0 -and $kind -ne 1) {{ continue }}
          EnableSharingSafe $connMap[$g].cfg $kind
        }}
        if ($privFirst -eq $true) {{ throw }}
      }}
    }}
    if (-not $applied) {{
      try {{
        if ($ZubcutTopology -ne 'hotspot') {{
          try {{
            Disable-NetAdapter -Name $down.Name -Confirm:$false -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
            Enable-NetAdapter -Name $down.Name -Confirm:$false -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
          }} catch {{}}
        }}
        $share3 = New-Object -ComObject HNetCfg.HNetShare
        $connMap = @{{}}
        foreach ($conn in @($share3.EnumEveryConnection())) {{
          try {{
            $props = $share3.NetConnectionProps($conn)
            $guid = NormGuid($props.Guid)
            $cfg = $share3.INetSharingConfigurationForINetConnection($conn)
            $connMap[$guid] = @{{ conn=$conn; cfg=$cfg; name=$props.Name }}
          }} catch {{ continue }}
        }}
        $upKey = Resolve-ConnGuid $upGuid $up.Name
        $dnKey = Resolve-ConnGuid $downGuid $down.Name
        if (-not $upKey -or -not $dnKey) {{ throw 'Sharing manager lost adapter mapping after adapter reset.' }}
        Apply-ICS $false
        Start-Sleep -Seconds 2
        if (-not (Verify-ICS)) {{
          throw 'ICS could not be verified after adapter reset (run ZubCut as Administrator and check adapters).'
        }}
        $applied = $true
      }} catch {{
        foreach ($k in $connMap.Keys) {{ DisableSharingSafe $connMap[$k].cfg }}
        foreach ($row in @($snapshot)) {{
          $g = NormGuid($row.guid)
          if (-not $connMap.ContainsKey($g)) {{ continue }}
          try {{ $kind = [System.Convert]::ToInt32($row.type) }} catch {{ continue }}
          if ($kind -ne 0 -and $kind -ne 1) {{ continue }}
          EnableSharingSafe $connMap[$g].cfg $kind
        }}
        throw
      }}
    }}
  }}
  catch {{
    foreach ($k in $connMap.Keys) {{ DisableSharingSafe $connMap[$k].cfg }}
    foreach ($row in @($snapshot)) {{
      $g = NormGuid($row.guid)
      if (-not $connMap.ContainsKey($g)) {{ continue }}
      try {{ $kind = [System.Convert]::ToInt32($row.type) }} catch {{ continue }}
      if ($kind -ne 0 -and $kind -ne 1) {{ continue }}
      EnableSharingSafe $connMap[$g].cfg $kind
    }}
    throw
  }}

  Start-Sleep -Seconds 2
  $dhcpOk = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
  if ($ZubcutTopology -eq 'hotspot' -and -not $dhcpOk) {{
    throw 'Mobile Hotspot is on but DHCP is not running. Toggle hotspot OFF then ON in Windows Settings, run ZubCut as Administrator, or use tools\\enable_hotspot_ics_now.ps1'
  }}
  $doneMsg = if ($ZubcutTopology -eq 'hotspot') {{ 'PC Mobile Hotspot ICS enabled (DHCP for PS5).' }} else {{ 'ICS sharing enabled.' }}
  Write-ClumsyState $up $down $snapshot $doneMsg
}}
catch {{
  $em = if ($null -ne $_.Exception) {{ $_.Exception.GetType().FullName + ': ' + $_.Exception.Message }} else {{ $_ | Out-String }}
  JsonOut @{{ ok=$false; error=$em }}
  exit 1
}}
"""
    ok, payload, raw = _run_powershell(script)
    if ok:
        return True, str(payload.get('message') or 'ICS sharing enabled.')
    msg = str(payload.get('error') or '').strip() or raw.strip() or 'ICS enable failed.'
    return False, msg


def repair_clumsy_network_sharing() -> Tuple[bool, str]:
    """
    Undo Clumsy ICS changes and restart Wi‑Fi / sharing services.

    Use when Mobile Hotspot stopped working after an older Clumsy enable attempt
    (those builds ran ``netsh wlan stop hostednetwork`` and reset ICS).
    """
    if os.name != 'nt':
        return True, 'Non-Windows platform; skipping repair.'
    if not _windows_is_admin():
        return (
            False,
            'Run ZubCut as Administrator to repair network sharing / Mobile Hotspot.',
        )
    state_path = _STATE_PATH.replace('\\', '\\\\')
    script = f"""
$ErrorActionPreference = 'Continue'
function NormGuid([object]$g) {{
  if ($null -eq $g) {{ return '' }}
  return ($g.ToString().Trim('{{','}}').ToLowerInvariant())
}}
function JsonOut([hashtable]$o) {{
  $json = $o | ConvertTo-Json -Compress -Depth 8
  Write-Output ('{_MARKER}' + $json)
}}
function SnapshotTypeInt($row) {{
  try {{ return [System.Convert]::ToInt32($row.type) }} catch {{ return -1 }}
}}
function SharingEnabledSafe($cfg) {{
  if ($null -eq $cfg) {{ return $false }}
  try {{
    $v = $cfg.SharingEnabled
    if ($null -eq $v) {{ return $false }}
    if ($v -is [bool]) {{ return $v }}
    try {{ return [bool][int]$v }} catch {{ return $false }}
  }} catch {{
    return $false
  }}
}}
function DisableSharingSafe([object]$cfg) {{
  if ($null -eq $cfg) {{ return }}
  if (-not (SharingEnabledSafe $cfg)) {{ return }}
  for ($i = 0; $i -lt 3; $i++) {{
    try {{ $cfg.DisableSharing(); return }} catch {{ Start-Sleep -Milliseconds 500 }}
  }}
}}
function EnableSharingSafe([object]$cfg, [int]$sharingKind) {{
  if ($null -eq $cfg) {{ return }}
  try {{
    $mi = $cfg.GetType().GetMethod('EnableSharing')
    if ($null -ne $mi) {{
      $parms = $mi.GetParameters()
      if ($parms.Length -eq 1) {{
        $enumType = $parms[0].ParameterType
        if ($enumType.IsEnum) {{
          $arg = [System.Enum]::ToObject($enumType, [int32]$sharingKind)
          $mi.Invoke($cfg, @($arg))
          return
        }}
      }}
    }}
  }} catch {{ }}
  try {{ $cfg.EnableSharing([int32]$sharingKind); return }} catch {{ }}
  try {{ $cfg.EnableSharing([uint32]$sharingKind); return }} catch {{ }}
  try {{ $cfg.EnableSharing($sharingKind); return }} catch {{ }}
}}
{_PS_ENSURE_WLAN_HEALTHY}
{_PS_HOTSPOT_HELPERS}
function Restart-NetworkSharingServicesSafe([bool]$preserveHotspot) {{
  $svcs = @('RemoteAccess', 'NlaSvc', 'iphlpsvc', 'wcmsvc')
  if (-not $preserveHotspot) {{
    $svcs = @('icssvc', 'SharedAccess') + $svcs
  }}
  foreach ($svc in $svcs) {{
    try {{
      $s = Get-Service -Name $svc -ErrorAction Stop
      if ($s.Status -eq 'Running') {{
        Restart-Service -Name $svc -Force -ErrorAction SilentlyContinue
      }} else {{
        Start-Service -Name $svc -ErrorAction SilentlyContinue
      }}
    }} catch {{}}
  }}
  if ($preserveHotspot) {{
    foreach ($svc in @('SharedAccess', 'icssvc')) {{
      try {{
        $s = Get-Service -Name $svc -ErrorAction Stop
        if ($s.Status -ne 'Running') {{
          Start-Service -Name $svc -ErrorAction SilentlyContinue
        }}
      }} catch {{}}
    }}
  }}
  Ensure-WlanAutoConfigHealthy | Out-Null
}}
try {{
  $snapshot = @()
  if (Test-Path "{state_path}") {{
    try {{
      $saved = Get-Content -Raw -Path "{state_path}" | ConvertFrom-Json
      if ($saved.snapshot) {{ $snapshot = @($saved.snapshot) }}
    }} catch {{}}
  }}

  $hotspotWasOn = (Test-MobileHotspotGateway) -or (Test-TetheringOn)

  Restart-NetworkSharingServicesSafe $hotspotWasOn
  Start-Sleep -Seconds 2

  # Never wipe ICS while Mobile Hotspot was on — PS5 gets Wi‑Fi but loses internet/NAT.
  $skipIcsReset = $hotspotWasOn
  if (-not $skipIcsReset) {{
    $share = New-Object -ComObject HNetCfg.HNetShare
    $connMap = @{{}}
    foreach ($conn in @($share.EnumEveryConnection())) {{
      try {{
        $props = $share.NetConnectionProps($conn)
        $guid = NormGuid($props.Guid)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        $connMap[$guid] = $cfg
      }} catch {{ continue }}
    }}
    foreach ($cfg in $connMap.Values) {{ DisableSharingSafe $cfg }}
    Start-Sleep -Milliseconds 800
    foreach ($row in @($snapshot)) {{
      $g = NormGuid($row.guid)
      if (-not $connMap.ContainsKey($g)) {{ continue }}
      $kind = SnapshotTypeInt $row
      if ($kind -ne 0 -and $kind -ne 1) {{ continue }}
      EnableSharingSafe $connMap[$g] $kind
    }}
  }}

  Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {{
    $d = ($_.Name + ' ' + $_.InterfaceDescription)
    if ($_.Status -eq 'Disabled' -and ($d -match 'Wi-Fi|Wireless|Wi-Fi Direct|Hosted')) {{
      try {{ Enable-NetAdapter -Name $_.Name -Confirm:$false -ErrorAction SilentlyContinue }} catch {{}}
    }}
  }}
  Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {{
    try {{
      Set-NetConnectionProfile -InterfaceIndex $_.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue
    }} catch {{}}
  }}

  Remove-Item -Path "{state_path}" -Force -ErrorAction SilentlyContinue

  Ensure-WlanAutoConfigHealthy | Out-Null
  $wlCheck = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
  if ($null -eq $wlCheck -or $wlCheck.Status -ne 'Running' -or $wlCheck.StartType -eq 'Manual' -or $wlCheck.StartType -eq 'Disabled') {{
    JsonOut @{{
      ok=$false
      error='WLAN AutoConfig (WlanSvc) is still not running. Open services.msc, set WLAN AutoConfig to Automatic, click Start, then reboot.'
    }}
    exit 1
  }}

  $hotspotReenabled = $false
  if ($hotspotWasOn -and -not (Test-TetheringOn)) {{
    $hotspotReenabled = Ensure-MobileHotspotOn
    Start-Sleep -Seconds 4
  }}
  $mobileHotspotActive = (Test-MobileHotspotGateway) -or (Test-TetheringOn)

    if ($hotspotWasOn) {{
    if (-not (Test-HotspotIcsActive)) {{
      Apply-HotspotIcsAutomated | Out-Null
      Start-Sleep -Seconds 2
    }}
    if (-not (Test-TetheringOn)) {{
      $hotspotReenabled = Ensure-MobileHotspotOn
      Start-Sleep -Seconds 4
    }}
    $dhcp67 = Test-HotspotDhcp67
    $icsOk = Test-HotspotIcsActive
    if ($hotspotReenabled) {{
      $msg = @(
        'Mobile Hotspot was turned back on automatically.'
        'Reconnect the PS5 to your PC hotspot Wi-Fi (not the router).'
      ) -join ' '
    }} elseif ($dhcp67 -and $icsOk) {{
      $msg = @(
        'Mobile Hotspot is active; restored internet sharing (ICS) for clients.'
        'If the PS5 still has no internet: forget the hotspot on the PS5, reconnect, or set manual IP 192.168.137.2 gateway 192.168.137.1 DNS 8.8.8.8.'
      ) -join ' '
    }} elseif ($dhcp67 -and -not $icsOk) {{
      $msg = @(
        'Mobile Hotspot DHCP is up but internet sharing (ICS) could not be enabled automatically.'
        'Try Repair hotspot / sharing again, or set Console connects via -> Ethernet (PS5 cable to PC LAN port).'
      ) -join ' '
    }} else {{
      $msg = @(
        'Mobile Hotspot is off after repair.'
        'Open Settings -> Network -> Mobile hotspot and turn it ON, then reconnect the PS5.'
      ) -join ' '
    }}
  }} else {{
    $msg = @(
      'Reset Internet Connection Sharing and restarted Wi-Fi / hotspot services.'
      'In Windows Settings: turn Mobile hotspot OFF, wait 10 seconds, turn it ON again.'
      'Then reconnect the PS5 to the PC hotspot Wi-Fi.'
    ) -join ' '
  }}
  JsonOut @{{ ok=$true; message=$msg }}
  exit 0
}}
catch {{
  $em = if ($null -ne $_.Exception) {{ $_.Exception.GetType().FullName + ': ' + $_.Exception.Message }} else {{ $_ | Out-String }}
  JsonOut @{{ ok=$false; error=$em }}
  exit 1
}}
"""
    ok, payload, raw = _run_powershell(script)
    if ok:
        return True, str(payload.get('message') or 'Network sharing repair completed.')
    msg = str(payload.get('error') or '').strip() or raw.strip() or 'Repair failed.'
    return False, msg


def ensure_wlan_autoconfig_healthy() -> Tuple[bool, str]:
    """
    Restore WLAN AutoConfig (WlanSvc) if an older build left it Manual or stopped.

    Safe to call repeatedly; does nothing when the service is already Automatic and running.
    """
    if os.name != 'nt':
        return True, 'Non-Windows platform; skipping.'
    if not _windows_is_admin():
        return (
            False,
            'Run ZubCut as Administrator to restore WLAN AutoConfig (Wi-Fi).',
        )
    script = f"""
$ErrorActionPreference = 'Continue'
function JsonOut([hashtable]$o) {{
  $json = $o | ConvertTo-Json -Compress -Depth 8
  Write-Output ('{_MARKER}' + $json)
}}
{_PS_ENSURE_WLAN_HEALTHY}
$fixed = Ensure-WlanAutoConfigHealthy
$wl = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
if ($null -eq $wl -or $wl.Status -ne 'Running') {{
  JsonOut @{{
    ok=$false
    fixed=$fixed
    error='WLAN AutoConfig (WlanSvc) is not running. Open services.msc, set WLAN AutoConfig to Automatic, click Start, then reboot.'
  }}
  exit 1
}}
if ($wl.StartType -eq 'Manual' -or $wl.StartType -eq 'Disabled') {{
  JsonOut @{{
    ok=$false
    fixed=$fixed
    error='WLAN AutoConfig startup type is still Manual or Disabled.'
  }}
  exit 1
}}
$msg = if ($fixed) {{ 'Restored WLAN AutoConfig (Wi-Fi).' }} else {{ 'WLAN AutoConfig already healthy.' }}
JsonOut @{{ ok=$true; fixed=$fixed; message=$msg }}
exit 0
"""
    ok, payload, _raw = _run_powershell(script)
    if ok:
        return True, str(payload.get('message') or 'WLAN AutoConfig OK.')
    return False, str(payload.get('error') or 'Could not verify WLAN AutoConfig.')


def maybe_ensure_wlan_autoconfig_on_startup() -> None:
    """Every launch (admin): undo WlanSvc damage from older ZubCut builds without full ICS repair."""
    if os.name != 'nt' or not _windows_is_admin():
        return
    try:
        ensure_wlan_autoconfig_healthy()
    except Exception:
        pass


def rollback_clumsy_ics() -> Tuple[bool, str]:
    return repair_clumsy_network_sharing()


def maybe_repair_stale_clumsy_ics_on_startup() -> None:
    """
    If Clumsy left a state file but mode is off, undo ICS changes automatically once at launch.
    Fixes PCs broken by older builds without requiring the user to find Repair in Settings.
    """
    if os.name != 'nt':
        return
    if not os.path.isfile(_STATE_PATH):
        return
    try:
        from tools.clumsy_inline import clumsy_mode_enabled

        if clumsy_mode_enabled():
            return
    except Exception:
        return
    if not _windows_is_admin():
        return
    repair_clumsy_network_sharing()
