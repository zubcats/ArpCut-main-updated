# PS5 Mobile Hotspot ON at 2.4 GHz + ICS when on Ethernet.
$ErrorActionPreference = 'Continue'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator (use PS5 Hotspot ON on the desktop).'
    exit 1
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

Write-Host '=== PS5 Hotspot ON (2.4 GHz) ==='

if (Test-EthernetInternetUplink) {
    if (Repair-Ps5HotspotEthernet) { exit 0 }
    exit 1
}

Write-Host 'Internet: Wi-Fi only (no Ethernet) — switching PC + hotspot to 2.4 GHz...'
Write-Host 'Tip: Plug Ethernet from PC to router for faster PC + reliable 2.4 GHz hotspot + sharing.'
$wifiOnly = Join-Path $PSScriptRoot '_switch_24ghz_only_now.ps1'
if (-not (Test-Path $wifiOnly)) {
    Write-Host "Missing $wifiOnly"
    exit 1
}
& $wifiOnly
exit $LASTEXITCODE
