$log = Join-Path $PSScriptRoot '_turn_hotspot_on_24.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }
'' | Set-Content $log
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Get-Content $log
    exit
}
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
Disconnect-WifiClientForEthernetHotspot | Out-Null
Set-MobileHotspotBandRegistry2Ghz | Out-Null
Start-Service SharedAccess,icssvc,WlanSvc -EA SilentlyContinue
if (Ensure-MobileHotspotOnRobust) {
    $m = Get-TetheringManager
    Configure-MobileHotspotAccessPoint2Ghz $m $false | Out-Null
    L "OK state=$($m.TetheringOperationalState) band=$(Get-MobileHotspotApBandLabel $m)"
    L "gw=$(Test-MobileHotspotGateway) dhcp=$(Test-HotspotDhcpListening)"
} else {
    L 'FAILED — Settings -> Mobile hotspot -> ON, band 2.4 GHz'
    exit 1
}
