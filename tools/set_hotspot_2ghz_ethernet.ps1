# Optional local tool — best setup for 5 GHz PC internet + 2.4 GHz hotspot on one USB Wi-Fi radio.
# 1. Plug Ethernet from PC to router (internet over cable).
# 2. Configure hotspot to 2.4 GHz and turn it on.
# 3. Connect PC Wi-Fi to router on 5 GHz (optional, for local LAN access).

$ErrorActionPreference = 'Continue'
Write-Host '=== Hotspot 2.4 GHz with Ethernet internet (recommended) ==='

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator'
    Read-Host 'Press Enter'
    exit 1
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

if (-not (Test-EthernetInternetUplink)) {
    Write-Host ''
    Write-Host 'Plug an Ethernet cable from this PC to your router first, then run this script again.'
    Write-Host 'Settings -> Network -> Ethernet should show Connected.'
    Write-Host ''
    Read-Host 'Press Enter'
    exit 1
}

Write-Host 'Ethernet is the internet uplink — configuring 2.4 GHz hotspot on Wi-Fi...'
$ok = Ensure-MobileHotspot2GhzBand
if ($ok) { Start-MobileHotspotAfter2GhzConfig | Out-Null }

Write-Host 'Connecting PC Wi-Fi to 5 GHz (optional, does not affect hotspot band)...'
if (Connect-WifiUplinkTo5Ghz) {
    Write-Host 'PC Wi-Fi is on 5 GHz.'
} else {
    Write-Host 'Wi-Fi 5 GHz connect skipped or failed — you can connect manually in Settings.'
}

$mgr = Get-TetheringManager
if ($mgr) {
    Write-Host "Hotspot: band=$(Get-MobileHotspotBandLabel $mgr) state=$($mgr.TetheringOperationalState)"
}
$ch = Get-WifiUplinkChannel
if ($ch -gt 14) { Write-Host "PC Wi-Fi channel: $ch (5 GHz)" }

if ($ok) {
    Write-Host 'SUCCESS: Internet over Ethernet, hotspot on 2.4 GHz.'
    exit 0
}
Read-Host 'Hotspot configure failed. Press Enter'
exit 1
