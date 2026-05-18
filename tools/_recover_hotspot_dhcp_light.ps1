# Lightweight PS5 DHCP recovery — does NOT touch HNetCfg/ICS Control Panel (avoids freezes).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_recover_hotspot_light.log'
function L($m) { $ts = Get-Date -Format 'HH:mm:ss'; $line = "[$ts] $m"; Write-Host $line; Add-Content $log $line -Encoding utf8 -EA SilentlyContinue }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    L 'UAC required — click Yes'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

'' | Set-Content $log -Force
L '=== Light hotspot DHCP recovery (no ICS COM) ==='

# Close hung network property sheets only (not all of Explorer)
Get-Process mmc -EA SilentlyContinue | Where-Object { $_.MainWindowTitle -match 'Properties|Sharing|Network' } |
    ForEach-Object { L "Stopping hung mmc $($_.Id)"; Stop-Process -Id $_.Id -Force -EA SilentlyContinue }

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
. (Join-Path $PSScriptRoot '_winrt_await.ps1')

# Wi-Fi radio on, not connected to router
$wifi = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Wireless LAN|802\.11' -and $_.InterfaceDescription -notmatch 'Direct|Hosted|Virtual'
} | Select-Object -First 1
if ($wifi -and $wifi.Status -eq 'Disabled') {
    L "Enabling $($wifi.Name)..."
    Enable-NetAdapter -Name $wifi.Name -Confirm:$false -EA SilentlyContinue
    Start-Sleep 4
}
if ($wifi) {
    netsh wlan disconnect interface="$($wifi.Name)" 2>$null | Out-Null
}

Set-HotspotDhcpRegistry
Ensure-HotspotDhcpFirewall
L 'DHCP registry + firewall OK'

# Start hotspot via WinRT only (no sharing reset)
$mgr = Get-TetheringManager
if ($mgr) {
    $state = $mgr.TetheringOperationalState.ToString()
    L "Tethering state: $state"
    if ($state -ne 'On') {
        L 'Starting Mobile Hotspot (WinRT)...'
        $null = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'Start' 45
        Start-Sleep 8
    }
} else {
    L 'WARN: WinRT tethering unavailable — turn hotspot ON in Settings'
}

$ap = Get-HotspotPrivateAdapter
if (-not $ap) {
    L 'ERROR: No hotspot adapter. Settings -> Mobile hotspot OFF 15 sec -> ON'
    exit 1
}
L "Hotspot NIC: $($ap.Name)"

# IPv6 off on hotspot only (PS5 IPv4 DHCP)
try {
    Disable-NetAdapterBinding -Name $ap.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
    L 'IPv6 disabled on hotspot adapter'
} catch {}

$ifIdx = $ap.ifIndex
$gw = Get-NetIPAddress -InterfaceIndex $ifIdx -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' }
if (-not $gw) {
    L 'Adding 192.168.137.1/24 (gateway missing — PS5 cannot DHCP without this)...'
    try {
        New-NetIPAddress -InterfaceIndex $ifIdx -IPAddress 192.168.137.1 -PrefixLength 24 -ErrorAction Stop | Out-Null
    } catch {
        L "  New-NetIPAddress: $($_.Exception.Message)"
    }
}

# Restart DHCP only if port 67 is down (Restart-Service can hang when ncpa Sharing is open)
$dhcpUp = [bool](Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue)
if (-not $dhcpUp) {
    L 'Restarting SharedAccess (DHCP not listening)...'
    Restart-Service SharedAccess -Force -EA SilentlyContinue
    Start-Sleep 5
} else {
    L 'DHCP already listening — skipping SharedAccess restart (avoids hang)'
}

$dhcp = Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue
if ($dhcp) {
    L "DHCP listening: $($dhcp.LocalAddress -join ', ')"
} else {
    L 'WARN: UDP 67 not listening — toggle hotspot OFF 15 sec ON in Settings, do not open Sharing tab'
}

Get-NetIPAddress -InterfaceIndex $ifIdx -AddressFamily IPv4 -EA SilentlyContinue |
    ForEach-Object { L "  IPv4: $($_.IPAddress)/$($_.PrefixLength)" }

L ''
L 'ICS: left as you set it manually (this script does not change Sharing).'
L 'PS5: Forget osps -> restart PS5 -> connect -> wait up to 2 min for IP'
L 'Done.'
