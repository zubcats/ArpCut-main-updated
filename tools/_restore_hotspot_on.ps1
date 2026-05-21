$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
Disconnect-WifiClientForEthernetHotspot | Out-Null
Set-MobileHotspotBandRegistry2Ghz | Out-Null
$mgr = Get-TetheringManager
Configure-MobileHotspotAccessPoint2Ghz $mgr $false | Out-Null
if (Start-MobileHotspotAfter2GhzConfig) {
    Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
    Ensure-HotspotDhcpFirewall
    Write-Host "OK: Hotspot ON, band=$(Get-MobileHotspotApBandLabel (Get-TetheringManager))"
    Write-Host "Gateway: $(Test-MobileHotspotGateway) DHCP: $(Test-HotspotDhcpListening)"
} else {
    Write-Host 'FAILED — Settings -> Mobile hotspot -> turn ON manually'
    exit 1
}
