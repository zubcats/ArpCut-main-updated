# Optional local tool — NOT part of ZubCut.
# Sets Mobile Hotspot to 2.4 GHz only, then puts PC Wi-Fi back on 5 GHz when possible.
#
# Recommended: Ethernet cable PC -> router for internet; USB Wi-Fi only for hotspot.
# On a single-radio USB adapter, 5 GHz PC + 2.4 GHz hotspot together is often not possible
# unless internet uses Ethernet (see tools\set_hotspot_2ghz_ethernet.ps1).

$ErrorActionPreference = 'Continue'
Write-Host '=== Hotspot 2.4 GHz (PC Wi-Fi stays on 5 GHz when possible) ==='

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator'
    Read-Host 'Press Enter'
    exit 1
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

if (Test-EthernetInternetUplink) {
    Write-Host 'Internet uplink: Ethernet (good — Wi-Fi can stay on 5 GHz while hotspot uses 2.4 GHz).'
} else {
    Write-Host 'Internet uplink: Wi-Fi (single USB radio may not do 5 GHz PC + 2.4 GHz hotspot at once).'
    Write-Host 'For best results use Ethernet to the router: tools\set_hotspot_2ghz_ethernet.ps1'
}

$ok = Ensure-MobileHotspot2GhzBand
# Leave hotspot OFF so PC Wi-Fi can use 5 GHz on a single USB radio (turn hotspot ON when PS5 needs it).
Stop-MobileHotspotIfOn | Out-Null
Start-Sleep -Seconds 2

if (-not (Test-EthernetInternetUplink)) {
    Write-Host 'Restoring PC Wi-Fi to 5 GHz (router connection)...'
    if (Connect-WifiUplinkTo5Ghz) {
        Write-Host 'PC Wi-Fi reconnected on 5 GHz.'
    } else {
        Write-Host 'Could not auto-connect to 5 GHz — in Settings connect Wifi1 to the 5 GHz band, or use Ethernet + set_hotspot_2ghz_ethernet.ps1'
    }
} else {
    Write-Host 'With Ethernet internet you can turn Mobile hotspot ON anytime (stays 2.4 GHz for clients).'
    if ($ok) { Start-MobileHotspotAfter2GhzConfig | Out-Null }
}

$mgr = Get-TetheringManager
if ($mgr) {
    Write-Host "Hotspot: state=$($mgr.TetheringOperationalState) band=$(Get-MobileHotspotBandLabel $mgr) ssid=$($mgr.Configuration.SsidPrefix)"
}
$ch = Get-WifiUplinkChannel
if ($ch -gt 0) {
    $bandLabel = if ($ch -le 14) { '2.4 GHz' } else { '5 GHz' }
    Write-Host "PC Wi-Fi channel: $ch ($bandLabel)"
}

if ($ok) {
    Write-Host ''
    Write-Host 'Done:'
    Write-Host '  • Hotspot is set to 2.4 GHz (for PS5).'
    Write-Host '  • PC Wi-Fi should stay on 5 GHz for everyday use.'
    Write-Host '  • When you need the PS5: Settings -> Mobile hotspot -> ON'
    Write-Host '  • When done: hotspot OFF to get fastest 5 GHz back on Wi-Fi-only setups'
    exit 0
}
Write-Host 'FAILED: Could not set hotspot to 2.4 GHz.'
Read-Host 'Press Enter'
exit 1
