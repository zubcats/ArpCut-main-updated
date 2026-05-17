# Wi-Fi-only: hotspot OFF, PC back on 5 GHz for daily use. Run as Admin after PS5.
$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator'
    exit 1
}

Write-Host 'Stopping hotspot and reconnecting PC Wi-Fi to 5 GHz...'
Stop-MobileHotspotIfOn | Out-Null
Start-Sleep -Seconds 3
if (Connect-WifiUplinkTo5Ghz) {
    $ch = Get-WifiUplinkChannel
    Write-Host "Done. PC channel: $ch $(if ($ch -gt 14) { '(5 GHz)' } else { '(still 2.4 — pick 5 GHz in Settings)' })"
} else {
    Write-Host 'Hotspot is off. In Windows Wi-Fi, connect Wifi1 to the 5 GHz network manually.'
}
