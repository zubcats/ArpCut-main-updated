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


def format_clumsy_ics_error(detail: str, *, topology: str | None = None) -> str:
    """User-facing hints for common ICS / HNetCfg failures (incl. HRESULT 0x80040201)."""
    topo = normalize_clumsy_topology(topology) if topology else read_clumsy_topology()
    d = (detail or '').strip()
    lines = [d] if d else []
    low = d.lower()
    if topo == 'hotspot':
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
    if ($downIpProbe -and $downIpProbe.IPAddress) {{
      Write-ClumsyState $up $down $snapshot 'PC Mobile Hotspot path ready (using active hotspot).'
    }}
    throw ('Mobile Hotspot is not active yet. Turn ON Mobile hotspot in Windows Settings, connect the PS5 to your PC hotspot Wi-Fi (not the router), then enable Clumsy mode again. ZubCut will not reset ICS in hotspot mode.')
  }}

  try {{ netsh wlan stop hostednetwork 2>$null | Out-Null }} catch {{}}
  try {{ Set-NetConnectionProfile -InterfaceIndex $up.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
  try {{ Set-NetConnectionProfile -InterfaceIndex $down.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
  try {{ Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }} catch {{}}

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
        try {{
          Disable-NetAdapter -Name $down.Name -Confirm:$false -ErrorAction SilentlyContinue
          Start-Sleep -Seconds 1
          Enable-NetAdapter -Name $down.Name -Confirm:$false -ErrorAction SilentlyContinue
          Start-Sleep -Seconds 3
        }} catch {{}}
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
  Write-ClumsyState $up $down $snapshot 'ICS sharing enabled.'
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
function Restart-NetworkSharingServicesSafe {{
  foreach ($svc in @('SharedAccess', 'RemoteAccess', 'NlaSvc', 'iphlpsvc', 'wcmsvc')) {{
    try {{
      $s = Get-Service -Name $svc -ErrorAction Stop
      if ($s.Status -eq 'Running') {{
        Restart-Service -Name $svc -Force -ErrorAction SilentlyContinue
      }} else {{
        Start-Service -Name $svc -ErrorAction SilentlyContinue
      }}
    }} catch {{}}
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

  Restart-NetworkSharingServicesSafe
  Start-Sleep -Seconds 2

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

  $msg = @(
    'Reset Internet Connection Sharing and restarted Wi-Fi / hotspot services.'
    'In Windows Settings: turn Mobile hotspot OFF, wait 10 seconds, turn it ON again.'
    'Then reconnect the PS5 to the PC hotspot Wi-Fi.'
  ) -join ' '
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
