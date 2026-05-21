. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
$m = Get-TetheringManager
if ($m) {
    Write-Host "Hotspot state: $($m.TetheringOperationalState)"
    Write-Host "Band: $(Get-MobileHotspotApBandLabel $m)"
    Write-Host "Max compatibility ON = usually 2.4 GHz; OFF = 5 GHz or Auto"
}
