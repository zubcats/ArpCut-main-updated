$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$log = Join-Path $root '_switch_24ghz_result.txt'
function L($m) { Add-Content $log $m -Encoding UTF8; Write-Host $m }
. (Join-Path $root '_hotspot_2ghz_apply.ps1')
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    L 'Need Admin'; exit 1
}
L '--- hotspot 2.4 ---'
Set-MobileHotspotBandRegistry2Ghz | Out-Null
Restart-IcssvcIfNeeded | Out-Null
$ch = Get-WifiUplinkChannel
L "PC channel: $ch"
$mgr = Get-TetheringManager
if (-not $mgr) { L 'no mgr'; exit 1 }
Configure-MobileHotspotAccessPoint2Ghz $mgr $false | Out-Null
if (Start-MobileHotspotAfter2GhzConfig) { L 'hotspot started' } else { L 'start failed - toggle ON in Settings' }
$m2 = Get-TetheringManager
if ($m2) {
    try { L "state=$($m2.TetheringOperationalState) ap=$($m2.GetCurrentAccessPointConfiguration().Band)" } catch {}
}
