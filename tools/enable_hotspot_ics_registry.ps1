$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_enable_ics_result.txt'
function L([string]$m) { Write-Host $m; $m | Add-Content $log -Encoding UTF8 }
'' | Set-Content $log -Encoding UTF8

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    L 'ERROR: Admin required'
    exit 1
}

L '=== Registry + service ICS repair ==='

$saParams = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
foreach ($pair in @(
        @{ N = 'ScopeAddress'; V = '192.168.137.1' },
        @{ N = 'ScopeAddressBackup'; V = '192.168.137.1' },
        @{ N = 'StandaloneDhcpAddress'; V = '192.168.137.1' },
        @{ N = 'StandaloneDhcpMask'; V = '255.255.255.0' }
    )) {
    try {
        Set-ItemProperty -Path $saParams -Name $pair.N -Value $pair.V -Type String -Force
        L "  set $($pair.N)=$($pair.V)"
    } catch { L "  warn $($pair.N): $($_.Exception.Message)" }
}

try {
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name 'IPEnableRouter' -Value 1 -Type DWord -Force
    L '  IPEnableRouter=1'
} catch {}

$up = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'Realtek|Wi-Fi|Wireless' -and $_.InterfaceDescription -notmatch 'Direct' } | Select-Object -First 1
$down = Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Wi-Fi Direct' } | Select-Object -First 1
if ($up) {
    netsh interface ipv4 set interface "$($up.Name)" forwarding=enabled 2>&1 | ForEach-Object { L "  $_" }
}
if ($down) {
    netsh interface ipv4 set interface "$($down.Name)" forwarding=enabled 2>&1 | ForEach-Object { L "  $_" }
}

Stop-Service icssvc -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-Service icssvc -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-Service WlanSvc -ErrorAction SilentlyContinue

try {
    Set-ItemProperty -Path 'HKCU:\Software\Microsoft\WCM\Tethering\Settings' -Name 'TetheringEnabled' -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue
} catch {}

$deadline = (Get-Date).AddSeconds(35)
while ((Get-Date) -lt $deadline) {
    $dhcp = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
    $gw = Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' }
    if ($dhcp -and $gw) { break }
    Start-Sleep -Seconds 2
}

$dhcp = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
$gw = Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' }
L "dhcp67=$([bool]$dhcp) gw137=$([bool]$gw)"
if ($dhcp) {
    L 'SUCCESS: DHCP running - reconnect PS5.'
    exit 0
}
L 'Still no DHCP - manual Sharing tab required on this Realtek adapter.'
Start-Process 'ncpa.cpl'
exit 1
