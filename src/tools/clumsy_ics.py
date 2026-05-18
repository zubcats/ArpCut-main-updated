from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, Tuple

from constants import DOCUMENTS_PATH

_STATE_PATH = os.path.join(DOCUMENTS_PATH, 'clumsy_ics_state.json')
_CLUMSY_SETTINGS_RESTART_MARKER = 'clumsy_settings_restart.flag'
_MARKER = 'ZUBCUT_JSON:'


def clumsy_settings_restart_marker_path() -> str:
    return os.path.join(DOCUMENTS_PATH, _CLUMSY_SETTINGS_RESTART_MARKER)


def mark_clumsy_settings_restart_pending() -> None:
    """Written before Settings-driven restart so startup does not clear clumsy_mode."""
    if os.name != 'nt':
        return
    try:
        os.makedirs(DOCUMENTS_PATH, exist_ok=True)
        path = clumsy_settings_restart_marker_path()
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('pending\n')
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass


def consume_clumsy_settings_restart_pending() -> bool:
    if not os.path.isfile(clumsy_settings_restart_marker_path()):
        return False
    try:
        os.remove(clumsy_settings_restart_marker_path())
    except OSError:
        pass
    return True


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


def describe_clumsy_console_path() -> str:
    """Human-readable path from last Clumsy enable (for Settings UI)."""
    state = read_clumsy_ics_state()
    topo = str(state.get('topology') or '').strip().lower()
    up = str(state.get('upstream_name') or '').strip()
    down = str(state.get('downstream_name') or '').strip()
    uplink = str(state.get('uplink_kind') or '').strip().lower()
    if topo == 'hotspot':
        if uplink == 'ethernet' or 'ethernet' in up.lower():
            return 'Ethernet → Mobile Hotspot (PS5 on PC hotspot Wi‑Fi)'
        return 'Wi‑Fi → Mobile Hotspot (PS5 on PC hotspot Wi‑Fi)'
    if topo == 'ethernet':
        up_l = up or 'Internet'
        down_l = down or 'Ethernet to console'
        return f'{up_l} → {down_l} (PS5 on LAN cable)'
    return 'Auto-detect when Clumsy mode is enabled'


def read_clumsy_topology() -> str:
    """Last detected console path from Clumsy enable (hotspot vs ethernet)."""
    state = read_clumsy_ics_state()
    t = str(state.get('topology') or '').strip().lower()
    if t in ('hotspot', 'ethernet'):
        return t
    try:
        from tools.utils_gui import get_settings

        legacy = str(get_settings('clumsy_topology') or '').strip().lower()
        if legacy in ('hotspot', 'ethernet'):
            return normalize_clumsy_topology(legacy)
    except Exception:
        pass
    return 'hotspot'


def _clumsy_error_has_hotspot_hints(detail: str) -> bool:
    low = (detail or '').lower()
    if 'valid hotspot path for clumsy mode' in low:
        return True
    return (
        ('connect the ps5' in low or 'connect your console' in low)
        and ('mobile hotspot' in low or 'clumsy mode does' in low)
    )


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
                'Valid hotspot path for Clumsy mode:',
                '• PC has internet on Wi‑Fi or Ethernet to your router',
                '• Mobile Hotspot is ON; console on PC hotspot Wi‑Fi (not home router)',
                '• Internet sharing: router adapter → hotspot adapter (ZubCut enables if missing)',
                '• Run ZubCut as Administrator, then enable Clumsy mode',
            ]
        )
    if topo == 'ethernet' and 'lan port' not in low and 'ethernet' not in low:
        lines.extend(
            [
                '',
                'For PS5 → Ethernet cable → this PC:',
                '• Plug the PS5 into a spare Ethernet port (not the port to your router)',
                '• Turn OFF Mobile Hotspot if you are using the cable',
                '• Run ZubCut as Administrator, then enable Clumsy mode again',
            ]
        )
    if 'repair hotspot' not in low and topo not in ('hotspot', 'ethernet'):
        lines.extend(
            [
                '',
                'Enable Clumsy mode in Settings (run as Administrator). ZubCut auto-detects a '
                'valid path: console on spare Ethernet, or console on PC Mobile Hotspot.',
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
  # Never Stop/Restart WlanSvc - that drops all Wi-Fi. Only fix when actually broken.
  $fixed = $false
  try {
    $wl = Get-Service -Name WlanSvc -ErrorAction Stop
    if ($wl.Status -eq 'Running' -and $wl.StartType -in @('Automatic', 'AutomaticDelayedStart')) {
      return $false
    }
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
    try {
      $wl2 = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
      if ($null -eq $wl2 -or $wl2.Status -ne 'Running') {
        Start-Service -Name WlanSvc -ErrorAction SilentlyContinue
      }
    } catch {}
    $fixed = $true
  }
  return $fixed
}
"""

# Hotspot: DHCP alone is not enough - PS5 needs ICS (Wi-Fi public -> Wi-Fi Direct private).
_PS_HOTSPOT_HELPERS = r"""
function NormGuidHotspot([object]$g) {
  if ($null -eq $g) { return '' }
  return ($g.ToString().Trim('{','}').ToLowerInvariant())
}
function IsVirtualNicLike([string]$name, [string]$desc) {
  $all = (($name + ' ' + $desc) -as [string]).ToLowerInvariant()
  return ($all -match 'hyper-v|vethernet|virtual|bluetooth|loopback|tap|vpn|wireguard|vmware|npcap|wi-fi direct|hosted network|mobile hotspot')
}
function LikelyEthernetNic($a) {
  $d = ($a.Name + ' ' + $a.InterfaceDescription)
  if ($d -match 'Ethernet|Gigabit|GbE|^LAN|USB.*Ethernet|RNDIS|PCIe.*Family|ASIX|AX88179') { return $true }
  try { if ($a.MediaType -eq '802.3') { return $true } } catch {}
  return $false
}
function IsHotspotDownstreamNic($a) {
  $all = (($a.Name + ' ' + $a.InterfaceDescription) -as [string]).ToLowerInvariant()
  return ($all -match 'wi-fi direct|hosted network|mobile hotspot|local area connection\\*|microsoft wi-fi direct')
}
function Get-InternetUplinkAdapter {
  $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric, InterfaceMetric
  $candidates = @()
  foreach ($rt in @($routes)) {
    try {
      $cand = Get-NetAdapter -InterfaceIndex $rt.InterfaceIndex -ErrorAction Stop
      if (-not $cand -or $cand.Status -ne 'Up') { continue }
      if (IsVirtualNicLike $cand.Name $cand.InterfaceDescription) { continue }
      if (IsHotspotDownstreamNic $cand) { continue }
      $candidates += $cand
    } catch {}
  }
  if ($candidates.Count -eq 0) { return $null }
  $eth = @($candidates | Where-Object { LikelyEthernetNic $_ } | Select-Object -First 1)
  if ($eth) { return $eth[0] }
  return $candidates[0]
}
function Get-GatewayIpForUplink($up) {
  if ($null -eq $up) { return '' }
  $rt = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceIndex -eq $up.ifIndex } | Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
  if ($rt -and $rt.NextHop) { return [string]$rt.NextHop }
  return ''
}
function Test-HotspotPathActive {
  if (Test-TetheringOn) { return $true }
  if (Test-MobileHotspotGateway) { return $true }
  return $false
}
function Get-HotspotDownstreamAdapter {
  param([int]$ExcludeIfIndex = -1)
  $down = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and $_.ifIndex -ne $ExcludeIfIndex -and (IsHotspotDownstreamNic $_)
  } | Sort-Object InterfaceMetric, ifIndex | Select-Object -First 1
  if ($down) { return $down }
  $gw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1
  if ($gw -and $gw.InterfaceIndex -ne $ExcludeIfIndex) {
    return Get-NetAdapter -InterfaceIndex $gw.InterfaceIndex -ErrorAction SilentlyContinue
  }
  return $null
}
function Test-ConsoleOnEthernetAdapter {
  param($Adapter, [string]$GatewayIp, [string[]]$UplinkIps, [string]$GwPrefix)
  $neighbors = @(Get-NetNeighbor -InterfaceIndex $Adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.IPAddress -and $_.IPAddress -notlike '169.254.*' -and $_.State -in @('Reachable','Stale','Permanent','Probe','Delay')
    })
  foreach ($n in $neighbors) {
    $nip = [string]$n.IPAddress
    if ($nip -eq $GatewayIp) { continue }
    if ($UplinkIps -contains $nip) { continue }
    if ($nip -match '\.255$') { continue }
    if ($GwPrefix -and $nip -match '^(\d+\.\d+\.\d+)\.\d+$' -and ($Matches[1] + '.') -eq $GwPrefix) { continue }
    return $true
  }
  return $false
}
function Find-EthernetConsoleAdapter {
  param($Uplink, [string]$GatewayIp)
  if ($null -eq $Uplink) { return $null }
  $upIdx = [int]$Uplink.ifIndex
  $upIps = @(Get-NetIPAddress -InterfaceIndex $upIdx -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { $_.IPAddress })
  $gwPrefix = ''
  if ($GatewayIp -match '^(\d+\.\d+\.\d+)\.\d+$') { $gwPrefix = $Matches[1] + '.' }
  $ethUp = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.ifIndex -ne $upIdx -and $_.Status -eq 'Up' -and (LikelyEthernetNic $_) -and -not (IsHotspotDownstreamNic $_) -and -not (IsVirtualNicLike $_.Name $_.InterfaceDescription)
  })
  # One spare Ethernet port (not the router uplink) - console cable path even before ARP shows a neighbor.
  if ($ethUp.Count -eq 1) { return $ethUp[0] }
  foreach ($a in $ethUp) {
    if (Test-ConsoleOnEthernetAdapter -Adapter $a -GatewayIp $GatewayIp -UplinkIps $upIps -GwPrefix $gwPrefix) {
      return $a
    }
  }
  return $null
}
function Get-UplinkKindLabel($adapter) {
  if ($null -eq $adapter) { return 'unknown' }
  if (LikelyEthernetNic $adapter) { return 'ethernet' }
  return 'wifi'
}
function Disconnect-WifiClientWhenEthernetUplink {
  $up = Get-InternetUplinkAdapter
  if ($null -eq $up -or -not (LikelyEthernetNic $up)) { return }
  $wlan = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'Wireless LAN' -and -not (IsHotspotDownstreamNic $_)
  } | Select-Object -First 1
  if ($wlan) {
    netsh wlan disconnect interface="$($wlan.Name)" 2>$null | Out-Null
    Start-Sleep -Seconds 2
  }
}
function Ensure-EthernetPreferredRouting {
  $up = Get-InternetUplinkAdapter
  if ($null -eq $up -or -not (LikelyEthernetNic $up)) { return }
  try {
    Set-NetIPInterface -InterfaceIndex $up.ifIndex -AddressFamily IPv4 -InterfaceMetric 10 -ErrorAction SilentlyContinue
  } catch {}
  foreach ($if in @(Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.ConnectionState -eq 'Connected' })) {
    $a = Get-NetAdapter -InterfaceIndex $if.InterfaceIndex -ErrorAction SilentlyContinue
    if (-not $a) { continue }
    $d = ($a.Name + ' ' + $a.InterfaceDescription)
    if ($d -match 'Wireless|Wi-Fi|WiFi|WLAN|802\.11' -and $d -notmatch 'Direct|Hosted') {
      try {
        Set-NetIPInterface -InterfaceIndex $if.InterfaceIndex -AddressFamily IPv4 -InterfaceMetric 5000 -ErrorAction SilentlyContinue
      } catch {}
    }
  }
}
function Test-HotspotConsoleReady {
  if (-not (Test-MobileHotspotGateway)) { return $false }
  $det = Detect-ClumsyConsolePath
  if (-not $det.Ok -or [string]$det.Path -ne 'hotspot') { return $false }
  $pair = @{ Up = $det.Up; Down = $det.Down }
  return (Test-IcsActiveForPair $pair)
}
function Prepare-ClumsyHotspotConsole {
  <#
  Enable sharing only when needed. Never disrupt a working hotspot (gateway + correct ICS pair).
  #>
  param([switch]$Force)
  if (-not $Force -and (Test-HotspotConsoleReady)) {
    Ensure-HotspotDhcpFirewall
    return @{ ok = $true; unchanged = $true }
  }
  Ensure-SharingServicesLight
  try {
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name IPEnableRouter -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue
  } catch {}
  $det = Detect-ClumsyConsolePath
  $pair = $null
  if ($det.Ok -and [string]$det.Path -eq 'hotspot') {
    $pair = @{ Up = $det.Up; Down = $det.Down }
  }
  $up = if ($pair) { $pair.Up } else { Get-InternetUplinkAdapter }
  if ($up) {
    try { Set-NetConnectionProfile -InterfaceIndex $up.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue } catch {}
  }
  $needIcs = (-not $pair) -or -not (Test-IcsActiveForPair $pair)
  if ($needIcs -and $up -and (LikelyEthernetNic $up)) {
    Disconnect-WifiClientWhenEthernetUplink
    Ensure-EthernetPreferredRouting
  }
  if (-not (Test-MobileHotspotGateway)) {
    return @{
      ok = $false
      error = 'Mobile Hotspot is not active. Turn it on in Windows Settings, then enable Clumsy mode again.'
    }
  }
  $down = Get-HotspotDownstreamAdapter
  if ($down) {
    try { Set-NetConnectionProfile -InterfaceIndex $down.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue } catch {}
  }
  Ensure-HotspotDhcpFirewall
  if (-not (Test-MobileHotspotGateway)) {
    return @{ ok = $false; error = 'Mobile Hotspot did not get 192.168.137.1. Toggle hotspot OFF 15 sec ON in Settings, then enable Clumsy mode again.' }
  }
  return @{ ok = $true }
}
function Detect-ClumsyConsolePath {
  $up = Get-InternetUplinkAdapter
  if (-not $up) {
    return @{ Ok=$false; Error='No internet adapter found. Connect this PC to your router (Wi-Fi or Ethernet), then try again.' }
  }
  $gw = Get-GatewayIpForUplink $up
  $uplinkKind = Get-UplinkKindLabel $up
  # PS5 on spare Ethernet port (not router WAN) - prefer over hotspot when a console is on the cable.
  $eth = Find-EthernetConsoleAdapter -Uplink $up -GatewayIp $gw
  if ($eth) {
    return @{ Ok=$true; Path='ethernet'; Up=$up; Down=$eth; GatewayIp=$gw; UplinkKind=$uplinkKind }
  }
  if (Test-HotspotPathActive) {
    $down = Get-HotspotDownstreamAdapter -ExcludeIfIndex $up.ifIndex
    if ($down) {
      return @{ Ok=$true; Path='hotspot'; Up=$up; Down=$down; GatewayIp=$gw; UplinkKind=$uplinkKind }
    }
    return @{ Ok=$false; Error='Mobile Hotspot is on but ZubCut could not find the hotspot adapter. Toggle hotspot off and on in Windows Settings, then try Clumsy mode again.' }
  }
  $uplinkHint = if ($uplinkKind -eq 'ethernet') { 'Ethernet to router' } else { 'Wi-Fi to router' }
  return @{
    Ok=$false
    Error=(
      'No valid console path detected. Set up one of these first, then enable Clumsy mode (Administrator):' +
      ' (A) Console on a spare Ethernet port - PC internet on ' + $uplinkHint + '; or' +
      ' (B) Mobile Hotspot ON - console on PC hotspot Wi-Fi, sharing from your internet adapter to the hotspot adapter.'
    )
  }
}
function Test-IcsActiveForPair($pair) {
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
  $det = Detect-ClumsyConsolePath
  if ($det.Ok) {
    return (Test-IcsActiveForPair @{ Up=$det.Up; Down=$det.Down })
  }
  $pair = Get-HotspotAdapterPair
  if ($null -eq $pair.Up -or $null -eq $pair.Down) { return $false }
  return (Test-IcsActiveForPair $pair)
}
function Get-HotspotAdapterPairForIcs {
  $det = Detect-ClumsyConsolePath
  if ($det.Ok) { return @{ Up=$det.Up; Down=$det.Down } }
  $up = Get-InternetUplinkAdapter
  $down = Get-HotspotDownstreamAdapter
  return @{ Up=$up; Down=$down }
}
function Apply-HotspotIcsCore($pair) {
  if ($null -eq $pair.Up -or $null -eq $pair.Down) { return $false }
  if (Test-IcsActiveForPair $pair) { return $true }
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
  function DisableSharingOnGuid($map, $g) {
    if (-not $map.ContainsKey($g)) { return }
    try { if ($map[$g].SharingEnabled) { $map[$g].DisableSharing() } } catch {}
  }
  # Only touch the detected uplink + hotspot pair - never wipe ICS on other adapters.
  DisableSharingOnGuid $connMap $upG
  DisableSharingOnGuid $connMap $dnG
  Start-Sleep -Milliseconds 400
  $ok = $false
  try {
    $connMap[$upG].EnableSharing(0)
    $connMap[$dnG].EnableSharing(1)
    $ok = $true
  } catch {}
  if (-not $ok) {
    DisableSharingOnGuid $connMap $upG
    DisableSharingOnGuid $connMap $dnG
    Start-Sleep -Milliseconds 400
    try {
      $connMap[$dnG].EnableSharing(1)
      $connMap[$upG].EnableSharing(0)
      $ok = $true
    } catch {}
  }
  Start-Sleep -Seconds 2
  return (Test-IcsActiveForPair $pair)
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
function Apply-MainWifiSharingForHotspot {
  return (Apply-InternetSharingForClumsy)
}
function Apply-InternetSharingForClumsy {
  $det = Detect-ClumsyConsolePath
  if (-not $det.Ok) { return $false }
  $pair = @{ Up = $det.Up; Down = $det.Down }
  if (Test-IcsActiveForPair $pair) { return $true }
  return (Apply-HotspotIcsCore $pair)
}
function Apply-HotspotIcsAutomated {
  if (Test-HotspotIcsActive) { return $true }
  if (Apply-MainWifiSharingForHotspot) { return $true }
  return (Apply-HotspotIcs)
}
function Initialize-WinRtAwaitHelpers {
  if ($script:ZubcutWinRtAwaitReady) { return $true }
  try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    $script:ZubcutAsTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() |
      Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Length -eq 1 } |
      Select-Object -First 1
    $script:ZubcutWinRtAwaitReady = ($null -ne $script:ZubcutAsTaskMethod)
    return $script:ZubcutWinRtAwaitReady
  } catch { return $false }
}
function Get-WinRtAsyncResultType([object]$asyncOp) {
  if ($null -eq $asyncOp) { return $null }
  foreach ($iface in $asyncOp.GetType().GetInterfaces()) {
    if ($iface.IsGenericType -and $iface.GetGenericTypeDefinition().FullName -eq 'Windows.Foundation.IAsyncOperation`1') {
      return $iface.GetGenericArguments()[0]
    }
  }
  return $null
}
function Complete-WinRtAsync($asyncOp, [string]$label, [int]$timeoutSec) {
  if ($null -eq $asyncOp) { return $null }
  if (-not (Initialize-WinRtAwaitHelpers)) { return $null }
  $resultType = Get-WinRtAsyncResultType $asyncOp
  if ($null -eq $resultType) { return $null }
  try {
    $asTask = $script:ZubcutAsTaskMethod.MakeGenericMethod(@($resultType)).Invoke($null, @($asyncOp))
    if (-not $asTask.Wait($timeoutSec * 1000)) { return $null }
    if ($asTask.IsFaulted) { return $null }
    return $asTask.Result
  } catch { return $null }
}
function Wait-TetheringAsync($op, [string]$label) {
  return ($null -ne (Complete-WinRtAsync $op $label 30))
}
function Ensure-TetheringWinRTLoaded {
  try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction SilentlyContinue
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
  } catch {
    return $false
  }
  return $true
}
function Get-TetheringManager {
  try {
    if (-not (Ensure-TetheringWinRTLoaded)) { return $null }
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
function Ensure-SharingServicesLight {
  # Start ICS/RAS if stopped only - never Restart wcmsvc/NlaSvc/iphlpsvc (drops Wi-Fi / internet).
  foreach ($svc in @('SharedAccess', 'icssvc', 'RemoteAccess')) {
    try {
      $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
      if ($null -ne $s -and $s.Status -ne 'Running') {
        Start-Service -Name $svc -ErrorAction SilentlyContinue
      }
    } catch {}
  }
}
function Ensure-HotspotDhcpFirewall {
  # ICS DHCP server (svchost SharedAccess on 192.168.137.1:67) - not covered by client DHCP rules.
  foreach ($r in @(
    @{N='ZubCut-ICS-DHCP-In';D='in';LP='67';RP='';RIP=''},
    @{N='ZubCut-ICS-DHCP-Out';D='out';LP='67';RP='';RIP=''},
    @{N='ZubCut-ICS-DHCP-Subnet-In';D='in';LP='67';RP='';RIP='192.168.137.0/24'},
    @{N='ZubCut-ICS-DHCP-Subnet-Out';D='out';LP='67,68';RP='';RIP='192.168.137.0/24'},
    @{N='ZubCut-ICS-DHCP-Client-In';D='in';LP='68';RP='';RIP='192.168.137.0/24'}
  )) {
    netsh advfirewall firewall delete rule name="$($r.N)" 2>$null | Out-Null
    $cmd = "netsh advfirewall firewall add rule name=`"$($r.N)`" dir=$($r.D) action=allow protocol=UDP enable=yes"
    if ($r.LP) { $cmd += " localport=$($r.LP)" }
    if ($r.RP) { $cmd += " remoteport=$($r.RP)" }
    if ($r.RIP) { $cmd += " remoteip=$($r.RIP)" }
    cmd /c $cmd 2>$null | Out-Null
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


def _compose_ps_script(*segments: str) -> str:
    """Join PS script parts without f-string parsing brace literals inside _PS_HOTSPOT_HELPERS."""
    return ''.join(segments)


def _run_powershell(script_body: str) -> Tuple[bool, Dict[str, Any], str]:
    fd, path = tempfile.mkstemp(prefix='zubcut_clumsy_', suffix='.ps1')
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        # UTF-8 BOM so Windows PowerShell 5.1 parses non-ASCII safely if any remain.
        with open(path, 'w', encoding='utf-8-sig') as f:
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


def purge_clumsy_stale_attack_blocks(extra_ips=None) -> dict:
    """
    Remove leftover Kill/Dupe/Lag firewall blocks and WinDivert gate (like Clumsy with no filters).
    Call before enabling Clumsy mode so the console can reach the internet.
    """
    summary: dict = {'firewall_rules_removed': 0, 'unblocked_ips': []}
    if not sys.platform.startswith('win'):
        return summary
    ips: set[str] = set()
    if extra_ips:
        for ip in extra_ips:
            s = str(ip or '').strip()
            if s:
                ips.add(s)
    try:
        import re
        import subprocess

        out = subprocess.check_output(['arp', '-a'], text=True, errors='replace', timeout=15)
        for m in re.finditer(r'\b(192\.168\.137\.\d{1,3})\b', out):
            ip = m.group(1)
            if not ip.endswith('.255') and ip != '192.168.137.1':
                ips.add(ip)
    except Exception:
        pass
    try:
        from tools.pfctl import teardown_all_zubcut_network_attacks

        summary = teardown_all_zubcut_network_attacks(extra_ips=sorted(ips))
    except Exception:
        pass
    try:
        from tools.ics_windivert_shaper import _windivert_sc_stop_and_delete

        _windivert_sc_stop_and_delete()
    except Exception:
        pass
    return summary


def prepare_pc_mobile_hotspot() -> Tuple[bool, str]:
    """
    Automated Clumsy-style hotspot prep: start hotspot, enable ICS to it, DHCP firewall rules.
    """
    if os.name != 'nt':
        return True, 'Non-Windows platform; skipping hotspot prep.'
    if not _windows_is_admin():
        return False, 'Run ZubCut as Administrator to prepare Mobile Hotspot.'

    script = _compose_ps_script(
        f"""
$ErrorActionPreference = 'Continue'
function JsonOut([hashtable]$o) {{
  $json = $o | ConvertTo-Json -Compress -Depth 8
  Write-Output ('{_MARKER}' + $json)
}}
""",
        _PS_HOTSPOT_HELPERS,
        """
if (Test-HotspotConsoleReady) {{
  JsonOut @{{ ok=$true; dhcp67=(Test-HotspotDhcp67); ics_ok=$true; message='Mobile Hotspot sharing already configured.' }}
  exit 0
}}
$prep = Prepare-ClumsyHotspotConsole
if (-not $prep.ok) {{
  JsonOut @{{ ok=$false; error=$prep.error }}
  exit 1
}}
$det = Detect-ClumsyConsolePath
if ($det.Ok -and [string]$det.Path -eq 'hotspot') {{
  $p = @{{ Up = $det.Up; Down = $det.Down }}
  if (-not (Test-IcsActiveForPair $p)) {{
    Apply-HotspotIcsCore $p | Out-Null
  }}
}}
if (Test-HotspotIcsActive) {{
  Start-Sleep -Seconds 2
  $dhcp67 = Test-HotspotDhcp67
  $icsOk = Test-HotspotIcsActive
  if ($icsOk) {{
    JsonOut @{{ ok=$true; dhcp67=$dhcp67; ics_ok=$true; message='Mobile Hotspot ready (sharing enabled).' }}
    exit 0
  }}
}}
JsonOut @{{
  ok=$false
  needs_manual_sharing=$true
  error='Could not enable internet sharing to Mobile Hotspot. Run ZubCut as Administrator and enable Clumsy mode again.'
}}
exit 1
""",
    )
    ok, payload, raw = _run_powershell(script)
    if ok:
        return True, str(payload.get('message') or 'Mobile Hotspot ready.')
    if payload.get('needs_manual_sharing'):
        return False, str(
            payload.get('error')
            or (
                'Automatic hotspot sharing could not be enabled. '
                'Enable Clumsy mode in Settings (Administrator), or use Ethernet (PS5 → LAN port) in Settings.'
            )
        )
    msg = str(payload.get('error') or '').strip() or raw.strip() or 'Hotspot preparation failed.'
    return False, msg


def ensure_clumsy_ics_enabled(topology: str | None = None) -> Tuple[bool, str]:
    """Enable ICS for Clumsy. Console path (hotspot vs ethernet) is auto-detected in PowerShell."""
    _ = topology  # legacy callers may pass manual topology; detection is automatic
    if os.name != 'nt':
        return True, 'Non-Windows platform; skipping ICS automation.'
    if not _windows_is_admin():
        return (
            False,
            'ZubCut must run as Administrator to enable Internet Connection Sharing. '
            'Close ZubCut, right-click the shortcut, choose Run as administrator, then try again.',
        )
    purge_clumsy_stale_attack_blocks()
    os.makedirs(DOCUMENTS_PATH, exist_ok=True)
    state_path = _STATE_PATH.replace('\\', '\\\\')
    script = _compose_ps_script(
        f"""
$ErrorActionPreference = 'Stop'
function NormGuid([object]$g) {{
  if ($null -eq $g) {{ return '' }}
  return ($g.ToString().Trim('{{','}}').ToLowerInvariant())
}}
function JsonOut([hashtable]$o) {{
  $json = $o | ConvertTo-Json -Compress -Depth 8
  Write-Output ('{_MARKER}' + $json)
}}
""",
        _PS_HOTSPOT_HELPERS,
        f"""
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

  try {{
    Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters' -Name IPEnableRouter -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue
  }} catch {{}}

  $detect = Detect-ClumsyConsolePath
  if (-not $detect.Ok) {{
    JsonOut @{{ ok=$false; error=$detect.Error }}
    exit 1
  }}
  $ZubcutTopology = [string]$detect.Path
  $ZubcutUplinkKind = [string]$detect.UplinkKind
  $up = $detect.Up
  $down = $detect.Down
  $upGuid = NormGuid($up.InterfaceGuid)
  $downGuid = NormGuid($down.InterfaceGuid)

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
    $uplinkKind = Get-UplinkKindLabel $up
    $state = @{{
      enabled_by_zubcut = $true
      topology = $ZubcutTopology
      uplink_kind = $uplinkKind
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

  if ($ZubcutTopology -ne 'hotspot') {{
    try {{ netsh wlan stop hostednetwork 2>$null | Out-Null }} catch {{}}
    try {{ Set-NetConnectionProfile -InterfaceIndex $up.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    try {{ Set-NetConnectionProfile -InterfaceIndex $down.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    try {{ Start-Service SharedAccess -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1 }} catch {{}}
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

  if ($ZubcutTopology -eq 'hotspot') {{
    try {{ Set-NetConnectionProfile -InterfaceIndex $up.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    try {{ Set-NetConnectionProfile -InterfaceIndex $down.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    $pair = @{{ Up=$up; Down=$down }}
  $alreadyOk = (Test-MobileHotspotGateway) -and (Test-IcsActiveForPair $pair)
  if ($alreadyOk) {{
    Ensure-HotspotDhcpFirewall
    $shareMsg = 'Clumsy mode ready (hotspot sharing already active). Connect your console to the PC hotspot Wi-Fi.'
  }} else {{
    if (-not (Test-MobileHotspotGateway)) {{
      throw 'Mobile Hotspot is not active. Turn it on in Windows Settings, then enable Clumsy mode again.'
    }}
    Ensure-HotspotDhcpFirewall
    if ($ZubcutUplinkKind -eq 'ethernet') {{
      Disconnect-WifiClientWhenEthernetUplink
      Ensure-EthernetPreferredRouting
    }}
    if (-not (Test-IcsActiveForPair $pair)) {{
      if (-not (Apply-HotspotIcsCore $pair)) {{
        throw 'Could not enable internet sharing to Mobile Hotspot. Check sharing points from your internet adapter to the hotspot adapter, then try Clumsy mode again.'
      }}
    }}
    if (-not (Verify-ICS)) {{
      Start-Sleep -Seconds 2
      if (-not (Apply-HotspotIcsCore $pair)) {{
        throw 'Internet sharing to Mobile Hotspot could not be verified. Fix sharing in Network Connections, then enable Clumsy mode again.'
      }}
    }}
    for ($w = 0; $w -lt 10; $w++) {{
      if (Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue) {{ break }}
      Start-Sleep -Seconds 1
    }}
    $shareMsg = if ($ZubcutUplinkKind -eq 'ethernet') {{
      'Clumsy mode ready: Ethernet -> Mobile Hotspot. Connect your console to the PC hotspot Wi-Fi.'
    }} else {{
      'Clumsy mode ready: Wi-Fi -> Mobile Hotspot. Connect your console to the PC hotspot Wi-Fi.'
    }}
  }}
    Write-ClumsyState $up $down $snapshot $shareMsg
  }} else {{
    try {{ Set-NetConnectionProfile -InterfaceIndex $down.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    try {{ Set-NetConnectionProfile -InterfaceIndex $up.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue }} catch {{}}
    $ethPair = @{{ Up=$up; Down=$down }}
    if (Test-IcsActiveForPair $ethPair) {{
      Write-ClumsyState $up $down $snapshot 'Clumsy: Ethernet console path (ICS already active).'
    }} else {{
      try {{
        try {{ Enable-NetAdapter -Name $down.Name -Confirm:$false -ErrorAction SilentlyContinue }} catch {{}}
        if (-not (Apply-HotspotIcsCore $ethPair)) {{
          throw 'Could not enable Internet Connection Sharing for the Ethernet console path.'
        }}
        if (-not (Verify-ICS)) {{
          Start-Sleep -Seconds 2
          if (-not (Apply-HotspotIcsCore $ethPair)) {{
            throw 'ICS for the Ethernet console path could not be verified. Check sharing on the router adapter and console port, then try again.'
          }}
        }}
      }} catch {{
        foreach ($row in @($snapshot)) {{
          $g = NormGuid($row.guid)
          if (-not $connMap.ContainsKey($g)) {{ continue }}
          try {{ $kind = [System.Convert]::ToInt32($row.type) }} catch {{ continue }}
          if ($kind -ne 0 -and $kind -ne 1) {{ continue }}
          EnableSharingSafe $connMap[$g].cfg $kind
        }}
        throw
      }}
      Write-ClumsyState $up $down $snapshot 'Clumsy: Ethernet console path (ICS enabled).'
    }}
  }}
}}
catch {{
  try {{
    if ($ZubcutTopology -eq 'hotspot') {{
      if (-not (Test-HotspotConsoleReady)) {{
        $pair = Detect-ClumsyConsolePath
        if ($pair.Ok -and [string]$pair.Path -eq 'hotspot') {{
          $p = @{{ Up = $pair.Up; Down = $pair.Down }}
          if (-not (Test-IcsActiveForPair $p)) {{
            Apply-HotspotIcsCore $p | Out-Null
          }}
        }}
      }}
    }}
  }} catch {{}}
  $em = if ($null -ne $_.Exception) {{ $_.Exception.GetType().FullName + ': ' + $_.Exception.Message }} else {{ $_ | Out-String }}
  JsonOut @{{ ok=$false; error=$em }}
  exit 1
}}
""",
    )
    ok, payload, raw = _run_powershell(script)
    if ok:
        return True, str(payload.get('message') or 'ICS sharing enabled.')
    msg = str(payload.get('error') or '').strip() or raw.strip() or 'ICS enable failed.'
    _retry_main_wifi_sharing_for_hotspot()
    return False, msg


def _retry_main_wifi_sharing_for_hotspot() -> None:
    """Best-effort: apply ICS for detected path only (does not start Mobile Hotspot)."""
    if os.name != 'nt':
        return
    script = _compose_ps_script(
        _PS_HOTSPOT_HELPERS,
        """
$ErrorActionPreference = 'Continue'
try {
  Apply-InternetSharingForClumsy | Out-Null
} catch {}
""",
    )
    try:
        _run_powershell(script)
    except Exception:
        pass


def repair_clumsy_network_sharing() -> Tuple[bool, str]:
    """
    Restore Mobile Hotspot / ICS sharing without restarting Wi‑Fi stack services.

    When hotspot is on: does not wipe ICS or restart wcmsvc/NlaSvc (avoids killing PC internet).
    When hotspot is off: may reset saved ICS snapshot only.
    """
    if os.name != 'nt':
        return True, 'Non-Windows platform; skipping repair.'
    if not _windows_is_admin():
        return (
            False,
            'Run ZubCut as Administrator to repair network sharing / Mobile Hotspot.',
        )
    state_path = _STATE_PATH.replace('\\', '\\\\')
    script = _compose_ps_script(
        f"""
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
""",
        _PS_ENSURE_WLAN_HEALTHY,
        _PS_HOTSPOT_HELPERS,
        f"""
try {{
  $snapshot = @()
  if (Test-Path "{state_path}") {{
    try {{
      $saved = Get-Content -Raw -Path "{state_path}" | ConvertFrom-Json
      if ($saved.snapshot) {{ $snapshot = @($saved.snapshot) }}
    }} catch {{}}
  }}

  $hotspotWasOn = (Test-MobileHotspotGateway) -or (Test-TetheringOn)

  Ensure-SharingServicesLight
  Start-Sleep -Seconds 1

  # Never wipe ICS while Mobile Hotspot was on - PS5 gets Wi-Fi but loses internet/NAT.
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

  $mobileHotspotActive = (Test-MobileHotspotGateway) -or (Test-TetheringOn)

  if ($hotspotWasOn) {{
    if (-not (Test-HotspotConsoleReady)) {{
      $det = Detect-ClumsyConsolePath
      if ($det.Ok -and [string]$det.Path -eq 'hotspot') {{
        $p = @{{ Up = $det.Up; Down = $det.Down }}
        if (-not (Test-IcsActiveForPair $p)) {{
          Apply-HotspotIcsCore $p | Out-Null
          Start-Sleep -Seconds 2
        }}
      }}
    }}
    $dhcp67 = Test-HotspotDhcp67
    $icsOk = Test-HotspotIcsActive
    if ($icsOk) {{
      $msg = 'Clumsy disabled. Left your Mobile Hotspot as-is; internet sharing is enabled for ZubCut.'
    }} elseif ($dhcp67) {{
      $msg = 'Clumsy disabled. Mobile Hotspot is on; enable Wi-Fi Sharing manually if the console has no internet.'
    }} else {{
      $msg = 'Clumsy disabled. Toggle Mobile Hotspot OFF then ON in Windows Settings if clients cannot connect.'
    }}
  }} else {{
    $msg = @(
      'Reset saved Internet Connection Sharing settings.'
      'Turn Mobile hotspot ON in Windows Settings, then reconnect the PS5 to the PC hotspot Wi-Fi.'
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
""",
    )
    ok, payload, raw = _run_powershell(script)
    if ok:
        return True, str(payload.get('message') or 'Network sharing repair completed.')
    msg = str(payload.get('error') or '').strip() or raw.strip() or 'Repair failed.'
    return False, msg


def _wlan_autoconfig_needs_heal() -> bool:
    """True only when WlanSvc is stopped or not set to start automatically."""
    if os.name != 'nt':
        return False
    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        q = subprocess.run(
            ['sc', 'query', 'WlanSvc'],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=flags,
        )
        out = ((q.stdout or '') + (q.stderr or '')).upper()
        if 'RUNNING' not in out:
            return True
        c = subprocess.run(
            ['sc', 'qc', 'WlanSvc'],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=flags,
        )
        cfg = ((c.stdout or '') + (c.stderr or '')).upper()
        if 'AUTO_START' in cfg or 'DELAYED_AUTO_START' in cfg:
            return False
        if 'DEMAND_START' in cfg or 'DISABLED' in cfg:
            return True
        return False
    except Exception:
        return False


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
    script = _compose_ps_script(
        f"""
$ErrorActionPreference = 'Continue'
function JsonOut([hashtable]$o) {{
  $json = $o | ConvertTo-Json -Compress -Depth 8
  Write-Output ('{_MARKER}' + $json)
}}
""",
        _PS_ENSURE_WLAN_HEALTHY,
        """
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
""",
    )
    ok, payload, _raw = _run_powershell(script)
    if ok:
        return True, str(payload.get('message') or 'WLAN AutoConfig OK.')
    return False, str(payload.get('error') or 'Could not verify WLAN AutoConfig.')


def maybe_ensure_wlan_autoconfig_on_startup() -> None:
    """
    Undo WlanSvc damage from older ZubCut builds only when the service is actually broken.
    Does not run on every launch when Wi-Fi is already healthy (avoids touching WlanSvc).
    """
    if os.name != 'nt' or not _windows_is_admin():
        return
    if not _wlan_autoconfig_needs_heal():
        return
    try:
        ensure_wlan_autoconfig_healthy()
    except Exception:
        pass


def rollback_clumsy_ics() -> Tuple[bool, str]:
    return repair_clumsy_network_sharing()


def reset_clumsy_mode_on_startup() -> None:
    """
    Clumsy is session-only across quit/relaunch: clear clumsy_mode on cold start.

    Settings enables ICS then restarts ZubCut; a marker file (and legacy
    clumsy_persist_across_restart) skips this once so the checkbox stays on.
    """
    if os.name != 'nt':
        return
    try:
        from tools.utils_gui import import_settings_as_dict, set_settings_many

        if consume_clumsy_settings_restart_pending():
            return
        raw = import_settings_as_dict()
        if bool(raw.get('clumsy_persist_across_restart')):
            set_settings_many({'clumsy_persist_across_restart': False})
            return
        if bool(raw.get('clumsy_mode')):
            set_settings_many({'clumsy_mode': False})
    except Exception:
        pass


def maybe_repair_stale_clumsy_ics_on_startup() -> None:
    """
    After Settings restart with Clumsy still on: re-apply hotspot/ICS prep.
    If Clumsy is off but state file remains: repair ethernet paths; drop hotspot marker only.
    """
    if os.name != 'nt':
        return
    if not os.path.isfile(_STATE_PATH):
        return
    try:
        from tools.clumsy_inline import clumsy_mode_enabled

        if clumsy_mode_enabled():
            # Do not re-run hotspot prep on every launch — that breaks users who already configured sharing.
            return
    except Exception:
        pass
    try:
        with open(_STATE_PATH, encoding='utf-8') as f:
            saved = json.load(f)
        if str(saved.get('topology') or '').strip().lower() == 'hotspot':
            os.remove(_STATE_PATH)
            return
    except Exception:
        pass
    if not _windows_is_admin():
        return
    repair_clumsy_network_sharing()
