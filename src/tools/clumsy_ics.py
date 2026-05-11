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


def ensure_clumsy_ics_enabled() -> Tuple[bool, str]:
    if os.name != 'nt':
        return True, 'Non-Windows platform; skipping ICS automation.'
    os.makedirs(DOCUMENTS_PATH, exist_ok=True)
    state_path = _STATE_PATH.replace('\\', '\\\\')
    script = f"""
$ErrorActionPreference = 'Stop'
function NormGuid([object]$g) {{
  if ($null -eq $g) {{ return '' }}
  return ($g.ToString().Trim('{{','}}').ToLowerInvariant())
}}
function IsVirtualLike([string]$name, [string]$desc) {{
  $all = (($name + ' ' + $desc) -as [string]).ToLowerInvariant()
  return ($all -match 'hyper-v|vethernet|virtual|bluetooth|loopback|tap|vpn|wireguard|vmware|npcap loopback')
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
function EnableSharingSafe([object]$cfg, [int]$sharingKind) {{
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
try {{
  # ICS / sharing: start related services (best-effort).
  foreach ($svc in @('RemoteAccess', 'SharedAccess', 'NlaSvc')) {{
    try {{ Set-Service -Name $svc -StartupType Manual -ErrorAction SilentlyContinue }} catch {{}}
    try {{ Start-Service -Name $svc -ErrorAction SilentlyContinue }} catch {{}}
  }}

  # Include USB/LAN adapters: using only HardwareInterface excludes some USB Ethernet NICs.
  $allAdapters = Get-NetAdapter -ErrorAction Stop | Where-Object {{
    if ($_.Status -eq 'Disabled') {{ return $false }}
    if (IsVirtualLike $_.Name $_.InterfaceDescription) {{ return $false }}
    $virtBad = $false
    try {{ if ($null -ne $_.Virtual -and $_.Virtual -eq $true) {{ $virtBad = $true }} }} catch {{ }}
    if ($virtBad) {{ return $false }}
    if ($_.HardwareInterface -eq $true) {{ return $true }}
    $d = ($_.Name + ' ' + $_.InterfaceDescription)
    if ($d -match 'USB|Ethernet|Gigabit|GbE|LAN|RNDIS|ASIX|AX88179|NDIS|Thunderbolt') {{ return $true }}
    return $false
  }}
  if (-not $allAdapters) {{ throw 'No usable adapters found for Clumsy sharing.' }}

  function LikelyEthernet($a) {{
    $d = ($a.Name + ' ' + $a.InterfaceDescription)
    if ($d -match 'Ethernet|Gigabit|GbE|^LAN|USB.*Ethernet|RNDIS|PCIe.*Family|ASIX|AX88179') {{ return $true }}
    try {{ if ($a.MediaType -eq '802.3') {{ return $true }} }} catch {{}}
    return $false
  }}

  # Downstream is the console-facing adapter: strongly prefer Ethernet / 802.3 media.
  $downCandidates = $allAdapters | Where-Object {{
    (LikelyEthernet $_) -and $_.Status -eq 'Up'
  }} | Sort-Object InterfaceMetric, ifIndex
  if (-not $downCandidates) {{
    $downCandidates = $allAdapters | Where-Object {{
      $_.Name -match 'Ethernet' -or $_.InterfaceDescription -match 'Ethernet'
    }} | Sort-Object InterfaceMetric, ifIndex
  }}
  if (-not $downCandidates) {{
    $downCandidates = $allAdapters | Where-Object {{ $_.Status -eq 'Up' }} | Sort-Object InterfaceMetric, ifIndex
  }}
  if (-not $downCandidates) {{
    $downCandidates = $allAdapters | Sort-Object InterfaceMetric, ifIndex
  }}
  $down = $downCandidates | Select-Object -First 1
  if ($null -eq $down) {{ throw 'Could not choose downstream adapter.' }}
  $downGuid = NormGuid($down.InterfaceGuid)

  # Upstream is the internet-facing adapter: default-route owner excluding downstream.
  $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric, InterfaceMetric
  $up = $null
  foreach ($rt in @($routes)) {{
    try {{
      $cand = Get-NetAdapter -InterfaceIndex $rt.InterfaceIndex -ErrorAction Stop
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

  function Apply-ICS([bool]$privateFirst) {{
    foreach ($k in $connMap.Keys) {{
      $cfg = $connMap[$k].cfg
      if (SharingEnabledSafe $cfg) {{ try {{ $cfg.DisableSharing() }} catch {{ }} }}
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
        foreach ($k in $connMap.Keys) {{
          $c = $connMap[$k].cfg
          if (SharingEnabledSafe $c) {{ try {{ $c.DisableSharing() }} catch {{ }} }}
        }}
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
        foreach ($k in $connMap.Keys) {{
          $cfg = $connMap[$k].cfg
          if (SharingEnabledSafe $cfg) {{ try {{ $cfg.DisableSharing() }} catch {{ }} }}
        }}
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
    foreach ($k in $connMap.Keys) {{
      $cfg = $connMap[$k].cfg
      if (SharingEnabledSafe $cfg) {{ try {{ $cfg.DisableSharing() }} catch {{ }} }}
    }}
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
  $downIpObj = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $down.ifIndex -ErrorAction SilentlyContinue |
    Where-Object {{ $_.IPAddress -and $_.IPAddress -notlike '169.254.*' }} |
    Sort-Object SkipAsSource | Select-Object -First 1
  $downIp = if ($downIpObj) {{ $downIpObj.IPAddress }} else {{ '' }}
  if (-not $downIp) {{ throw 'ICS sharing enabled but downstream IPv4 not assigned.' }}
  $prefix = ''
  if ($downIp -match '^(\\d+\\.\\d+\\.\\d+)\\.') {{ $prefix = $Matches[1] + '.' }}
  if (-not $prefix) {{ throw 'ICS sharing enabled but could not determine downstream prefix.' }}

  $state = @{{
    enabled_by_zubcut = $true
    upstream_guid = $upGuid
    upstream_name = $up.Name
    downstream_guid = $downGuid
    downstream_name = $down.Name
    downstream_ipv4 = $downIp
    downstream_prefix = $prefix
    snapshot = $snapshot
    ts = (Get-Date).ToUniversalTime().ToString('o')
  }}
  $state | ConvertTo-Json -Depth 8 | Set-Content -Path "{state_path}" -Encoding UTF8
  JsonOut @{{ ok=$true; message='ICS sharing enabled.'; state=$state }}
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
        return True, str(payload.get('message') or 'ICS sharing enabled.')
    msg = str(payload.get('error') or '').strip() or raw.strip() or 'ICS enable failed.'
    return False, msg


def rollback_clumsy_ics() -> Tuple[bool, str]:
    if os.name != 'nt':
        return True, 'Non-Windows platform; skipping rollback.'
    state = read_clumsy_ics_state()
    if not state:
        return True, 'No previous ICS state to restore.'
    state_path = _STATE_PATH.replace('\\', '\\\\')
    script = f"""
$ErrorActionPreference = 'Stop'
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
function EnableSharingSafe([object]$cfg, [int]$sharingKind) {{
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
try {{
  if (-not (Test-Path "{state_path}")) {{
    JsonOut @{{ ok=$true; message='No rollback state file.' }}
    exit 0
  }}
  $state = Get-Content -Raw -Path "{state_path}" | ConvertFrom-Json
  $share = New-Object -ComObject HNetCfg.HNetShare
  $connMap = @{{}}
  foreach ($conn in @($share.EnumEveryConnection())) {{
    try {{
      $props = $share.NetConnectionProps($conn)
      $guid = NormGuid($props.Guid)
      $cfg = $share.INetSharingConfigurationForINetConnection($conn)
      $connMap[$guid] = @{{ conn=$conn; cfg=$cfg; name=$props.Name }}
    }} catch {{ continue }}
  }}
  foreach ($k in $connMap.Keys) {{
    $cfg = $connMap[$k].cfg
    if (SharingEnabledSafe $cfg) {{ try {{ $cfg.DisableSharing() }} catch {{ }} }}
  }}
  foreach ($row in @($state.snapshot)) {{
    $g = NormGuid($row.guid)
    if (-not $connMap.ContainsKey($g)) {{ continue }}
    $kind = SnapshotTypeInt $row
    if ($kind -ne 0 -and $kind -ne 1) {{ continue }}
    EnableSharingSafe $connMap[$g].cfg $kind
  }}
  Remove-Item -Path "{state_path}" -Force -ErrorAction SilentlyContinue
  JsonOut @{{ ok=$true; message='Restored previous ICS sharing state.' }}
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
        return True, str(payload.get('message') or 'Rollback completed.')
    msg = str(payload.get('error') or '').strip() or raw.strip() or 'Rollback failed.'
    return False, msg
