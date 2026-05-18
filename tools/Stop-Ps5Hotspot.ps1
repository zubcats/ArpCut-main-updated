# PS5 Mobile Hotspot OFF.
# Ethernet uplink: hotspot off only. Wi-Fi-only: hotspot off + PC back on 5 GHz when possible.
$ErrorActionPreference = 'Continue'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator'
    exit 1
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

Write-Host '=== PS5 Hotspot OFF ==='
Stop-MobileHotspotIfOn | Out-Null
Start-Sleep -Seconds 2

if (Test-EthernetInternetUplink) {
    Write-Host 'Hotspot OFF. PC internet stays on Ethernet.'
    if (Restore-WifiClientAfterHotspot) {
        Write-Host 'PC Wi-Fi reconnected to router (5 GHz when possible).'
    }
    exit 0
}

if (Test-Path (Join-Path $PSScriptRoot '_wifi_band_lock.ps1')) {
    . (Join-Path $PSScriptRoot '_wifi_band_lock.ps1')
    Restore-PcWifiNormal | Out-Null
    exit 0
}

if (Connect-WifiUplinkTo5Ghz) {
    $ch = Get-WifiUplinkChannel
    Write-Host "Hotspot OFF. PC Wi-Fi channel $ch $(if ($ch -gt 14) { '(5 GHz)' } else { '(still 2.4)' })."
} else {
    Write-Host 'Hotspot OFF. In Wi-Fi settings, connect Wifi1 to 5 GHz if needed.'
}
exit 0
