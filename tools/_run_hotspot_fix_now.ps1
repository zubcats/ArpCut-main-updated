# Non-interactive hotspot ICS + DHCP fix (one-shot for agent)
$ErrorActionPreference = 'Continue'
$logPath = Join-Path $PSScriptRoot '_hotspot_fix_log.txt'
function L([string]$m) { Write-Host $m; Add-Content -Path $logPath -Value $m -ErrorAction SilentlyContinue }
'' | Set-Content -Path $logPath -Force

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
L "Running as Administrator: $isAdmin"
if (-not $isAdmin) {
    L 'ERROR: Need Administrator. Re-run elevated.'
    exit 1
}

function NormGuid($g) {
    if ($null -eq $g) { return '' }
    return ($g.ToString().Trim('{', '}').ToLowerInvariant())
}
function EnableShare($cfg, [int]$kind) {
    try { $cfg.EnableSharing([int32]$kind); return $true } catch {}
    try { $cfg.EnableSharing($kind); return $true } catch {}
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
    if (-not $down) { $down = Get-HotspotGatewayAdapter }
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
function Test-HotspotIcsActive([hashtable]$resolved) {
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

L '=== Before ==='
$gwBefore = Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' }
L ('  192.168.137.1: ' + [bool]$gwBefore)
L ('  DHCP UDP 67: ' + (Test-Dhcp67))

Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' } | ForEach-Object {
    $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
    if ($a -and $a.InterfaceDescription -notmatch 'Direct|Hosted' -and $a.Name -notmatch 'Local Area Connection') {
        L "Removing stale 192.168.137.1 from $($a.Name)"
        Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -EA SilentlyContinue
    }
}

foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc', 'Dhcp')) {
    try { Start-Service $svc -ErrorAction SilentlyContinue } catch {}
}

$resolved = Resolve-HotspotAdapters
$up = $resolved.Up
$down = $resolved.Down
L "Upstream: $($up.Name)"
L "Downstream: $($down.Name)"
L ('  ICS pair active: ' + (Test-HotspotIcsActive $resolved))

if ((Test-Dhcp67) -and (Test-HotspotIcsActive $resolved)) {
    L '=== SUCCESS: DHCP + ICS already OK ==='
    exit 0
}

if (-not $down) {
    L 'WARN: Hotspot adapter not Up. Turn Mobile hotspot ON in Settings, then re-run.'
    exit 2
}
if (-not $up) {
    L 'ERROR: No upstream internet adapter found.'
    exit 3
}

L 'Applying ICS (Wi-Fi public -> hotspot private)...'
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
$upK = $null; $dnK = $null
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
    $icsOk = (EnableShare $connMap[$upK].cfg 0) -and (EnableShare $connMap[$dnK].cfg 1)
    if (-not $icsOk) {
        foreach ($k in $connMap.Keys) {
            try { if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing() } } catch {}
        }
        Start-Sleep -Milliseconds 500
        $icsOk = (EnableShare $connMap[$dnK].cfg 1) -and (EnableShare $connMap[$upK].cfg 0)
    }
}

# Firewall DHCP rules (from clumsy_ics)
@(
    @{N='ZubCut-DHCP-In';D='in';P=67}, @{N='ZubCut-DHCP-Out';D='out';P=67},
    @{N='ZubCut-DHCPClient-In';D='in';P=68}, @{N='ZubCut-DHCPClient-Out';D='out';P=68}
) | ForEach-Object {
    netsh advfirewall firewall delete rule name="$($_.N)" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="$($_.N)" dir=$($_.D) action=allow protocol=UDP localport=$($_.P) enable=yes | Out-Null
}
netsh advfirewall firewall delete rule name="ZubCut-Hotspot-Subnet-In" 2>$null | Out-Null
netsh advfirewall firewall add rule name="ZubCut-Hotspot-Subnet-In" dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name="ZubCut-Hotspot-Subnet-Out" dir=out action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null

$saParams = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
foreach ($pair in @('ScopeAddress', 'ScopeAddressBackup', 'StandaloneDhcpAddress')) {
    try { Set-ItemProperty -Path $saParams -Name $pair -Value '192.168.137.1' -Type String -Force -EA SilentlyContinue } catch {}
}
try {
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name 'IPEnableRouter' -Value 1 -Type DWord -Force -EA SilentlyContinue
} catch {}

Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 6

L '=== After ==='
L ('  192.168.137.1: ' + [bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' }))
L ('  DHCP UDP 67: ' + (Test-Dhcp67))
$resolved2 = Resolve-HotspotAdapters
L ('  ICS pair active: ' + (Test-HotspotIcsActive $resolved2))

if ((Test-Dhcp67) -and (Test-HotspotIcsActive $resolved2)) {
    L '=== SUCCESS: Reconnect PS5 to PC hotspot ==='
    exit 0
}
if (Test-Dhcp67) {
    L '=== PARTIAL: DHCP OK but ICS pair wrong — toggle hotspot OFF 15s ON ==='
    exit 4
}
L '=== FAIL: Toggle Mobile hotspot OFF 15s ON, then re-run ==='
exit 5
