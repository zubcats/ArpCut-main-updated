$out = Join-Path $PSScriptRoot '_start_hotspot_verbose.log'
function W($m) { $m | Tee-Object -FilePath $out -Append }
'' | Set-Content $out
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
$m = Get-TetheringManager
W "Manager: $(if ($m) { 'yes' } else { 'no' })"
if (-not $m) { exit 1 }
W "Before: $($m.TetheringOperationalState) band=$(Get-MobileHotspotApBandLabel $m)"
Set-MobileHotspotBandRegistry2Ghz | Out-Null
Configure-MobileHotspotAccessPoint2Ghz $m $false | Out-Null
$op = $m.StartTetheringAsync()
$ok = Wait-WinRtAsync $op 'Start' 60
W "StartTethering wait: $ok"
Start-Sleep 10
$m2 = Get-TetheringManager
W "After: $($m2.TetheringOperationalState) band=$(Get-MobileHotspotApBandLabel $m2)"
W "137.1: $(Test-MobileHotspotGateway) dhcp67: $(Test-HotspotDhcpListening)"
