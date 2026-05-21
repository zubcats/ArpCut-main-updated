# Turn ON "Maximize compatibility" = hotspot 2.4 GHz (revert).
$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
Disconnect-WifiClientForEthernetHotspot | Out-Null
if (Force-MobileHotspot2Ghz -DisconnectWifiClientIfEthernet) {
    Write-Host 'SUCCESS: Maximize compatibility ON (2.4 GHz)'
    Write-Host "Band: $(Get-MobileHotspotApBandLabel (Get-TetheringManager))"
} else {
    Write-Host 'FAILED — toggle hotspot in Settings to 2.4 GHz manually'
    exit 1
}
