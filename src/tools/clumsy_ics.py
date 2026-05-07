from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any, Dict, Tuple

from constants import DOCUMENTS_PATH

_STATE_PATH = os.path.join(DOCUMENTS_PATH, 'clumsy_ics_state.json')
_MARKER = 'ZUBCUT_JSON:'


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
        proc = subprocess.run(
            [
                'powershell',
                '-NoProfile',
                '-ExecutionPolicy',
                'Bypass',
                '-File',
                path,
            ],
            capture_output=True,
            text=True,
        )
        out = (proc.stdout or '') + '\n' + (proc.stderr or '')
        payload: Dict[str, Any] = {}
        for line in reversed(out.splitlines()):
            if line.startswith(_MARKER):
                try:
                    payload = json.loads(line[len(_MARKER):].strip())
                except Exception:
                    payload = {}
                break
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
  Write-Output '{_MARKER}' + ($o | ConvertTo-Json -Compress -Depth 8)
}}
try {{
  # Ensure ICS service is available.
  try {{ Set-Service -Name SharedAccess -StartupType Manual -ErrorAction SilentlyContinue }} catch {{}}
  try {{ Start-Service -Name SharedAccess -ErrorAction SilentlyContinue }} catch {{}}

  $allAdapters = Get-NetAdapter -ErrorAction Stop | Where-Object {{
    $_.HardwareInterface -eq $true -and -not (IsVirtualLike $_.Name $_.InterfaceDescription)
  }}
  if (-not $allAdapters) {{ throw 'No physical adapters found for Clumsy sharing.' }}

  # Downstream is the console-facing adapter: strongly prefer Ethernet.
  $downCandidates = $allAdapters | Where-Object {{
    ($_.Name -match 'Ethernet' -or $_.InterfaceDescription -match 'Ethernet') -and $_.Status -eq 'Up'
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
    $props = $share.NetConnectionProps($conn)
    $guid = NormGuid($props.Guid)
    $cfg = $share.INetSharingConfigurationForINetConnection($conn)
    $connMap[$guid] = @{{ conn=$conn; cfg=$cfg; name=$props.Name }}
    if ($cfg.SharingEnabled) {{
      $snapshot += @{{ guid=$guid; type=[int]$cfg.SharingConnectionType; name=$props.Name }}
    }}
  }}
  if (-not $connMap.ContainsKey($upGuid)) {{ throw 'Upstream adapter not found in sharing manager.' }}
  if (-not $connMap.ContainsKey($downGuid)) {{ throw 'Downstream adapter not found in sharing manager.' }}

  try {{
    foreach ($k in $connMap.Keys) {{
      $cfg = $connMap[$k].cfg
      if ($cfg.SharingEnabled) {{ $cfg.DisableSharing() }}
    }}
    $connMap[$upGuid].cfg.EnableSharing(0)   # Public (internet-facing)
    $connMap[$downGuid].cfg.EnableSharing(1) # Private (downstream)
  }}
  catch {{
    # Roll back immediately if apply failed midway.
    foreach ($k in $connMap.Keys) {{
      $cfg = $connMap[$k].cfg
      if ($cfg.SharingEnabled) {{ $cfg.DisableSharing() }}
    }}
    foreach ($row in @($snapshot)) {{
      $g = NormGuid($row.guid)
      if (-not $connMap.ContainsKey($g)) {{ continue }}
      $kind = [int]$row.type
      if ($kind -ne 0 -and $kind -ne 1) {{ continue }}
      $connMap[$g].cfg.EnableSharing($kind)
    }}
    throw
  }}

  Start-Sleep -Seconds 3
  $downIpObj = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $down.ifIndex -ErrorAction SilentlyContinue |
    Where-Object {{ $_.IPAddress -and $_.IPAddress -notlike '169.254.*' }} |
    Sort-Object SkipAsSource | Select-Object -First 1
  $downIp = if ($downIpObj) {{ $downIpObj.IPAddress }} else {{ '' }}
  $prefix = ''
  if ($downIp -match '^(\\d+\\.\\d+\\.\\d+)\\.') {{ $prefix = $Matches[1] + '.' }}

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
  JsonOut @{{ ok=$false; error=$_.Exception.Message }}
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
  Write-Output '{_MARKER}' + ($o | ConvertTo-Json -Compress -Depth 8)
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
    $props = $share.NetConnectionProps($conn)
    $guid = NormGuid($props.Guid)
    $cfg = $share.INetSharingConfigurationForINetConnection($conn)
    $connMap[$guid] = @{{ conn=$conn; cfg=$cfg; name=$props.Name }}
  }}
  foreach ($k in $connMap.Keys) {{
    $cfg = $connMap[$k].cfg
    if ($cfg.SharingEnabled) {{ $cfg.DisableSharing() }}
  }}
  foreach ($row in @($state.snapshot)) {{
    $g = NormGuid($row.guid)
    if (-not $connMap.ContainsKey($g)) {{ continue }}
    $kind = [int]$row.type
    if ($kind -ne 0 -and $kind -ne 1) {{ continue }}
    $connMap[$g].cfg.EnableSharing($kind)
  }}
  Remove-Item -Path "{state_path}" -Force -ErrorAction SilentlyContinue
  JsonOut @{{ ok=$true; message='Restored previous ICS sharing state.' }}
  exit 0
}}
catch {{
  JsonOut @{{ ok=$false; error=$_.Exception.Message }}
  exit 1
}}
"""
    ok, payload, raw = _run_powershell(script)
    if ok:
        return True, str(payload.get('message') or 'Rollback completed.')
    msg = str(payload.get('error') or '').strip() or raw.strip() or 'Rollback failed.'
    return False, msg
