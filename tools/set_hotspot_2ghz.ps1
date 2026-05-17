# Optional local tool — NOT part of ZubCut. ONE entry point for hotspot band setup.
#
# Wi-Fi-only (your USB radio): run this once to save profile, then ALWAYS use:
#   _wifi_only_ps5_hotspot_on.ps1  before PS5  |  _wifi_only_ps5_hotspot_off.ps1  after
# Do NOT turn hotspot ON only in Windows Settings while PC is on 5 GHz — it will show 5 GHz.
#
# Ethernet internet: PC can stay on 5 GHz; this script can start 2.4 GHz hotspot directly.

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

$eth = Test-EthernetInternetUplink
Stop-MobileHotspotIfOn | Out-Null
Start-Sleep -Seconds 2

if ($eth) {
    Write-Host 'Ethernet: configuring 2.4 GHz hotspot (PC Wi-Fi can stay on 5 GHz).'
    $ok = Ensure-MobileHotspot2GhzBand
    if ($ok) { Start-MobileHotspotAfter2GhzConfig | Out-Null }
} else {
    Write-Host 'Wi-Fi-only USB radio: saving 2.4 GHz hotspot profile (PC will use 2.4 while hotspot is on).'
    Write-Host '  For PS5: run tools\_wifi_only_ps5_hotspot_on.ps1  (Admin)'
    Write-Host '  After play: run tools\_wifi_only_ps5_hotspot_off.ps1  (Admin)'
    Set-MobileHotspotBandRegistry2Ghz | Out-Null
    Restart-IcssvcIfNeeded | Out-Null
    if (Move-UplinkWifiTo24GhzIfNeeded) {
        $mgr = Get-TetheringManager
        $ok = $false
        if ($mgr) { $ok = Configure-MobileHotspotAccessPoint2Ghz $mgr $false }
        Stop-MobileHotspotIfOn | Out-Null
        Start-Sleep -Seconds 2
        Write-Host 'Restoring PC to 5 GHz for daily use (hotspot stays OFF until PS5 script)...'
        Connect-WifiUplinkTo5Ghz | Out-Null
    } else {
        $ok = $false
        Write-Host 'Could not reach router on 2.4 GHz — in Wi-Fi settings connect to the 2.4 GHz band of Wifi1 first.'
    }
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
    if ($eth) {
        Write-Host 'Done (Ethernet): Hotspot can stay 2.4 GHz. PC Wi-Fi may stay on 5 GHz.'
    } else {
        Write-Host 'Done (Wi-Fi-only): Profile saved. Hotspot is OFF; PC back on 5 GHz for daily use.'
        Write-Host '  BEFORE PS5:  tools\_wifi_only_ps5_hotspot_on.ps1   (Admin — do not use Settings ON alone)'
        Write-Host '  AFTER PS5:   tools\_wifi_only_ps5_hotspot_off.ps1  (Admin)'
    }
    exit 0
}
Write-Host 'FAILED: Could not set hotspot to 2.4 GHz.'
Read-Host 'Press Enter'
exit 1
