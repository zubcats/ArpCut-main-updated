# Enable ICS: Wi-Fi (internet) -> Mobile Hotspot adapter so PS5 gets DHCP.
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_enable_ics_result.txt'
function L([string]$m) { $m | Tee-Object -FilePath $log -Append }
'' | Set-Content $log -Encoding UTF8

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    L 'ERROR: Run as Administrator'
    exit 1
}

function NormGuid($g) {
    if ($null -eq $g) { return '' }
    return ($g.ToString().Trim('{', '}').ToLowerInvariant())
}

foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc', 'Dhcp')) {
    try { Start-Service $svc -ErrorAction SilentlyContinue } catch {}
}

$down = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    (Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |
        Where-Object { $_.IPAddress -eq '192.168.137.1' })
} | Select-Object -First 1

if (-not $down) {
    $down = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
        $_.InterfaceDescription -match 'Wi-Fi Direct' -and $_.Status -eq 'Up'
    } | Select-Object -First 1
}

$routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -EA SilentlyContinue |
    Sort-Object RouteMetric, InterfaceMetric
$up = $null
foreach ($rt in @($routes)) {
    $cand = Get-NetAdapter -InterfaceIndex $rt.InterfaceIndex -EA SilentlyContinue
    if ($cand -and $cand.ifIndex -ne $down.ifIndex -and $cand.Status -eq 'Up') {
        $up = $cand
        break
    }
}
if (-not $up) { L 'ERROR: No upstream internet adapter'; exit 1 }
if (-not $down) { L 'ERROR: Turn ON Mobile Hotspot first (no 192.168.137.1 adapter)'; exit 1 }

L "Upstream: $($up.Name) | Downstream: $($down.Name)"

$share = New-Object -ComObject HNetCfg.HNetShare
$connMap = @{}
foreach ($conn in @($share.EnumEveryConnection())) {
    try {
        $props = $share.NetConnectionProps($conn)
        $guid = NormGuid($props.Guid)
        $connMap[$guid] = @{ cfg = $share.INetSharingConfigurationForINetConnection($conn); name = $props.Name }
    } catch {}
}

$upGuid = NormGuid((Get-NetAdapter -InterfaceIndex $up.ifIndex).InterfaceGuid)
$dnGuid = NormGuid((Get-NetAdapter -InterfaceIndex $down.ifIndex).InterfaceGuid)
$upKey = $null
$dnKey = $null
foreach ($k in $connMap.Keys) {
    if ($k -eq $upGuid) { $upKey = $k }
    if ($k -eq $dnGuid) { $dnKey = $k }
}
if (-not $upKey) {
    $want = $up.Name.ToLowerInvariant()
    foreach ($k in $connMap.Keys) {
        if (($connMap[$k].name -as [string]).ToLowerInvariant() -eq $want) { $upKey = $k; break }
    }
}
if (-not $dnKey) {
    $want = $down.Name.ToLowerInvariant()
    foreach ($k in $connMap.Keys) {
        if (($connMap[$k].name -as [string]).ToLowerInvariant() -eq $want) { $dnKey = $k; break }
    }
}
if (-not $upKey -or -not $dnKey) { L 'ERROR: Adapter not in sharing manager'; exit 1 }

foreach ($k in $connMap.Keys) {
    try { if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing() } } catch {}
}
Start-Sleep -Milliseconds 500

function EnableShare($cfg, [int]$kind) {
    try { $cfg.EnableSharing([int32]$kind); return } catch {}
    try { $cfg.EnableSharing($kind); return } catch {}
    throw 'EnableSharing failed'
}

try {
    EnableShare $connMap[$upKey].cfg 0
    EnableShare $connMap[$dnKey].cfg 1
    L 'ICS enabled: public upstream + private downstream'
} catch {
    L "WARN order 1: $($_.Exception.Message) — trying reverse"
    foreach ($k in $connMap.Keys) {
        try { if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing() } } catch {}
    }
    Start-Sleep -Milliseconds 500
    EnableShare $connMap[$dnKey].cfg 1
    EnableShare $connMap[$upKey].cfg 0
    L 'ICS enabled (reverse order)'
}

Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5

$dhcp = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
$gw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1
L "dhcp67=$([bool]$dhcp) gw137=$([bool]$gw)"
if ($dhcp) {
    L 'SUCCESS: DHCP is running. Reconnect PS5 to PC hotspot.'
    exit 0
}
L 'ICS on but DHCP still missing — toggle Mobile Hotspot OFF 15s ON, then reconnect PS5'
exit 1
