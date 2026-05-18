# Enable ICS: Ethernet (internet) -> Mobile hotspot (PS5). Starts hotspot first if needed.
$ErrorActionPreference = 'Continue'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator'
    exit 1
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

Write-Host '=== Enable hotspot sharing over Ethernet ==='
if (-not (Test-EthernetInternetUplink)) {
    Write-Host 'ERROR: Ethernet is not the internet connection. Plug in the cable first.'
    exit 1
}

Write-Host 'Ensuring Mobile Hotspot is ON...'
if (-not (Ensure-MobileHotspotOnRobust)) {
    Write-Host 'FAILED: Turn Mobile hotspot ON in Settings, wait 10s, run this again.'
    exit 1
}

if (Enable-EthernetHotspotIcs) {
    Show-Ps5HotspotStatus | Out-Null
    Write-Host ''
    Write-Host 'SUCCESS: Sharing enabled. Connect PS5 to osps and test connection.'
    exit 0
}
Show-EthernetHotspotIcsManualSteps
exit 1
