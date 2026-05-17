# Enable ICS while Mobile Hotspot stays ON (do not stop icssvc).
$ErrorActionPreference = 'Continue'
function L([string]$m) { Write-Host $m }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    L 'ERROR: Run as Administrator'
    Read-Host 'Press Enter to close'
    exit 1
}

function NormGuid($g) {
    if ($null -eq $g) { return '' }
    return ($g.ToString().Trim('{', '}').ToLowerInvariant())
}
function EnableShare($cfg, [int]$kind) {
    try { $cfg.EnableSharing([int32]$kind); return $true } catch {
        L "    EnableSharing($kind): $($_.Exception.Message)"
    }
    try { $cfg.EnableSharing($kind); return $true } catch {
        L "    EnableSharing alt: $($_.Exception.Message)"
    }
    return $false
}
function Test-Dhcp67 { return [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue) }
function Get-HotspotGatewayAdapter {
    foreach ($ip in @(Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' })) {
        $a = Get-NetAdapter -InterfaceIndex $ip.InterfaceIndex -EA SilentlyContinue
        if ($a -and ($a.InterfaceDescription -match 'Direct|Hosted' -or $a.Name -match 'Local Area Connection')) {
            return $a
        }
    }
    return $null
}
function Resolve-HotspotAdapters {
    $down = Get-NetAdapter -EA SilentlyContinue | Where-Object {
        $_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection\*'
    } | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1
    if (-not $down) {
        $down = Get-HotspotGatewayAdapter
    }
    $up = $null
    $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -EA SilentlyContinue |
        Sort-Object RouteMetric, InterfaceMetric
    foreach ($rt in @($routes)) {
        $cand = Get-NetAdapter -InterfaceIndex $rt.InterfaceIndex -EA SilentlyContinue
        if ($cand -and $cand.Status -eq 'Up' -and (-not $down -or $cand.ifIndex -ne $down.ifIndex)) {
            if ($cand.InterfaceDescription -notmatch 'Direct|Bluetooth|Virtual|Hyper-V') {
                $up = $cand
                break
            }
        }
    }
    if (-not $up) {
        $up = Get-NetAdapter -EA SilentlyContinue | Where-Object {
            $_.Status -eq 'Up' -and ($_.Name -eq 'Wi-Fi' -or $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi')
            $_.InterfaceDescription -notmatch 'Direct|Virtual|Bluetooth'
        } | Select-Object -First 1
    }
    return @{ Up = $up; Down = $down }
}

L '=== ZubCut hotspot fix (keeps Mobile Hotspot ON) ==='

# Remove stale 192.168.137.1 on wrong adapters (breaks hotspot detection).
Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' } | ForEach-Object {
    $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
    if ($a -and $a.InterfaceDescription -notmatch 'Direct|Hosted' -and $a.Name -notmatch 'Local Area Connection') {
        L "Removing stale 192.168.137.1 from $($a.Name)"
        Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -EA SilentlyContinue
    }
}

$resolved = Resolve-HotspotAdapters
$up = $resolved.Up
$down = $resolved.Down

if (-not $down) {
    L 'Hotspot adapter not ready. Turn Mobile hotspot ON in Settings.'
    Start-Process 'ms-settings:network-mobilehotspot'
    Read-Host 'Turn hotspot ON, wait 10 sec, press Enter'
    $resolved = Resolve-HotspotAdapters
    $up = $resolved.Up
    $down = $resolved.Down
}

if (-not $up -or -not $down) {
    L 'ERROR: Could not find adapters. Current list:'
    Get-NetAdapter -EA SilentlyContinue | ForEach-Object { L "  $($_.Name) | $($_.Status) | $($_.InterfaceDescription)" }
    Read-Host 'Press Enter to close'
    exit 1
}

foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc', 'Dhcp')) {
    try { Start-Service $svc -ErrorAction SilentlyContinue } catch {}
}
L "Upstream: $($up.Name)"
L "Downstream: $($down.Name)"

function Test-HotspotIcsActive {
    $up = $resolved.Up
    $down = $resolved.Down
    if (-not $up -or -not $down) { return $false }
    $upG = NormGuid((Get-NetAdapter -InterfaceIndex $up.ifIndex).InterfaceGuid)
    $dnG = NormGuid((Get-NetAdapter -InterfaceIndex $down.ifIndex).InterfaceGuid)
    $share = New-Object -ComObject HNetCfg.HNetShare
    $upPublic = $false
    $dnPrivate = $false
    foreach ($conn in @($share.EnumEveryConnection())) {
        try {
            $p = $share.NetConnectionProps($conn)
            $g = NormGuid $p.Guid
            $cfg = $share.INetSharingConfigurationForINetConnection($conn)
            if (-not $cfg.SharingEnabled) { continue }
            $st = [int]$cfg.SharingConnectionType
            if ($g -eq $upG -and $st -eq 0) { $upPublic = $true }
            if ($g -eq $dnG -and $st -eq 1) { $dnPrivate = $true }
        } catch {}
    }
    return ($upPublic -and $dnPrivate)
}

if ((Test-Dhcp67) -and (Test-HotspotIcsActive)) {
    L 'SUCCESS: DHCP and internet sharing (ICS) are active. Reconnect PS5 if needed.'
    Read-Host 'Press Enter to close'
    exit 0
}
if (Test-Dhcp67) {
    L 'DHCP is running but ICS routing is missing — PS5 may connect with no internet. Re-applying ICS...'
}

L 'Clearing old ICS on all adapters...'
$share = New-Object -ComObject HNetCfg.HNetShare
$connMap = @{}
foreach ($conn in @($share.EnumEveryConnection())) {
    try {
        $p = $share.NetConnectionProps($conn)
        $connMap[(NormGuid $p.Guid)] = @{ cfg = $share.INetSharingConfigurationForINetConnection($conn); name = $p.Name }
    } catch {}
}
foreach ($k in $connMap.Keys) {
    try { if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing(); L "  disabled $($connMap[$k].name)" } } catch {}
}
Start-Sleep -Seconds 1

$upG = NormGuid((Get-NetAdapter -InterfaceIndex $up.ifIndex).InterfaceGuid)
$dnG = NormGuid((Get-NetAdapter -InterfaceIndex $down.ifIndex).InterfaceGuid)
$upK = $null
$dnK = $null
foreach ($k in $connMap.Keys) {
    if ($k -eq $upG) { $upK = $k }
    if ($k -eq $dnG) { $dnK = $k }
}
if (-not $upK) {
    $w = $up.Name.ToLowerInvariant()
    foreach ($k in $connMap.Keys) { if (($connMap[$k].name -as [string]).ToLowerInvariant() -eq $w) { $upK = $k } }
}
if (-not $dnK) {
    $w = $down.Name.ToLowerInvariant()
    foreach ($k in $connMap.Keys) { if (($connMap[$k].name -as [string]).ToLowerInvariant() -eq $w) { $dnK = $k } }
}

$icsOk = $false
if ($upK -and $dnK) {
    L 'Enabling ICS (Wi-Fi public -> hotspot private)...'
    $icsOk = (EnableShare $connMap[$upK].cfg 0) -and (EnableShare $connMap[$dnK].cfg 1)
    if (-not $icsOk) {
        L 'Trying reverse order...'
        foreach ($k in $connMap.Keys) {
            try { if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing() } } catch {}
        }
        Start-Sleep -Milliseconds 500
        $icsOk = (EnableShare $connMap[$dnK].cfg 1) -and (EnableShare $connMap[$upK].cfg 0)
    }
} else {
    L "ERROR: sharing keys up=$upK dn=$dnK"
}

Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 6

L "gw137=$([bool](Get-HotspotGatewayAdapter)) dhcp67=$(Test-Dhcp67)"
if (Test-Dhcp67) {
    L 'SUCCESS: DHCP running. Reconnect PS5 to PC hotspot.'
    Read-Host 'Press Enter to close'
    exit 0
}

L ''
L 'Automatic ICS failed on this driver (normal for Realtek USB Wi-Fi).'
L 'Opening Network Connections - do this ONCE:'
L '  1. Right-click Wi-Fi -> Properties -> Sharing tab'
L '  2. Check "Allow other network users..."'
L '  3. Home network: pick "Local Area Connection*" (Wi-Fi Direct)'
L '  4. OK'
L '  5. Mobile hotspot OFF 15 sec ON, reconnect PS5'
Start-Process 'ncpa.cpl'
Read-Host 'Press Enter after you clicked OK on Sharing tab'
Start-Sleep -Seconds 5
L "After manual step: dhcp67=$(Test-Dhcp67)"
if (Test-Dhcp67) { L 'SUCCESS: DHCP is up now.' } else { L 'Toggle hotspot OFF/ON once more.' }
Read-Host 'Press Enter to close'
exit 1
