# Turn ON Mobile Hotspot, apply ICS, verify DHCP — non-interactive, must be Admin
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_hotspot_fix_log.txt'
function L([string]$m) { Write-Host $m; Add-Content $log $m }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    L 'Re-launch elevated...'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

'' | Set-Content $log
L "=== Turn on hotspot + ICS $(Get-Date -Format o) ==="

function NormGuid($g) {
    if ($null -eq $g) { return '' }
    return ($g.ToString().Trim('{', '}').ToLowerInvariant())
}
function Test-Dhcp67 { return [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue) }

# WinRT tethering
Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction SilentlyContinue
[void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
[void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Length -eq 1 } | Select-Object -First 1

function Wait-Async($op, [int]$sec) {
    if ($null -eq $op) { return $null }
    foreach ($iface in $op.GetType().GetInterfaces()) {
        if ($iface.IsGenericType -and $iface.GetGenericTypeDefinition().FullName -eq 'Windows.Foundation.IAsyncOperation`1') {
            $rt = $iface.GetGenericArguments()[0]
            $task = $asTask.MakeGenericMethod(@($rt)).Invoke($null, @($op))
            if (-not $task.Wait($sec * 1000)) { return $null }
            if ($task.IsFaulted) { return $null }
            return $task.Result
        }
    }
    return $null
}

$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if (-not $profile) { L 'ERROR: No internet connection profile (connect Wi-Fi first)'; exit 1 }
$mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
L ('Tethering state: ' + $mgr.TetheringOperationalState)

if ($mgr.TetheringOperationalState.ToString() -ne 'On') {
    L 'Starting Mobile Hotspot...'
    $null = Wait-Async ($mgr.StartTetheringAsync()) 45
    Start-Sleep -Seconds 8
    L ('Tethering state after start: ' + $mgr.TetheringOperationalState)
}

foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc')) {
    try { Start-Service $svc -ErrorAction SilentlyContinue } catch {}
}

$saParams = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
foreach ($pair in @('ScopeAddress', 'ScopeAddressBackup', 'StandaloneDhcpAddress')) {
    Set-ItemProperty -Path $saParams -Name $pair -Value '192.168.137.1' -Type String -Force -EA SilentlyContinue
}

$gw = $false
for ($i = 0; $i -lt 12; $i++) {
    $gw = [bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' })
    if ($gw) { break }
    Start-Sleep -Seconds 2
}
L ('192.168.137.1: ' + $gw)
if (-not $gw) { L 'ERROR: Hotspot gateway missing after start'; exit 2 }

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
$up = Get-EthernetUplinkAdapter
if (-not $up) {
    $up = Get-NetAdapter -EA SilentlyContinue | Where-Object {
        $_.Status -eq 'Up' -and ($_.Name -eq 'Wi-Fi' -or $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi')
        $_.InterfaceDescription -notmatch 'Direct|Virtual|Bluetooth'
    } | Select-Object -First 1
}
$down = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection')
} | Select-Object -First 1
L "Upstream: $($up.Name)"
L "Downstream: $($down.Name)"

$share = New-Object -ComObject HNetCfg.HNetShare
$connMap = @{}
foreach ($conn in @($share.EnumEveryConnection())) {
    try {
        $p = $share.NetConnectionProps($conn)
        $connMap[(NormGuid $p.Guid)] = @{ cfg = $share.INetSharingConfigurationForINetConnection($conn); name = $p.Name }
    } catch {}
}
$upG = NormGuid $up.InterfaceGuid
$dnG = NormGuid $down.InterfaceGuid
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

# Only clear ICS if pair not already correct
$needIcs = $true
if ($upK -and $dnK) {
    try {
        $uCfg = $connMap[$upK].cfg; $dCfg = $connMap[$dnK].cfg
        if ($uCfg.SharingEnabled -and $dCfg.SharingEnabled) {
            $ust = [int]$uCfg.SharingConnectionType; $dst = [int]$dCfg.SharingConnectionType
            if ($ust -eq 0 -and $dst -eq 1) { $needIcs = $false; L 'ICS already on correct pair' }
        }
    } catch {}
}

if ($needIcs -and $upK -and $dnK) {
    $icsLabel = if ($up.InterfaceDescription -match 'Ethernet|Gigabit|GbE') { 'Ethernet public -> hotspot private' } else { 'Wi-Fi public -> hotspot private' }
    L "Enabling ICS ($icsLabel)..."
    foreach ($k in $connMap.Keys) {
        try { if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing() } } catch {}
    }
    Start-Sleep -Seconds 1
    try {
        $connMap[$upK].cfg.EnableSharing(0)
        $connMap[$dnK].cfg.EnableSharing(1)
    } catch {
        L "EnableSharing: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 3
}

@(
    @{N='ZubCut-DHCP-In';D='in';P=67}, @{N='ZubCut-DHCP-Out';D='out';P=67}
) | ForEach-Object {
    netsh advfirewall firewall delete rule name="$($_.N)" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="$($_.N)" dir=$($_.D) action=allow protocol=UDP localport=$($_.P) enable=yes | Out-Null
}

Start-Service SharedAccess -ErrorAction SilentlyContinue
Start-Sleep -Seconds 8

L '=== Result ==='
L ('  192.168.137.1: ' + [bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' }))
L ('  DHCP UDP 67: ' + (Test-Dhcp67))
if (Test-Dhcp67) {
    L 'SUCCESS — reconnect PS5 to PC hotspot now'
    exit 0
}
L 'DHCP still down — toggle hotspot OFF 15s ON in Settings once'
exit 3
