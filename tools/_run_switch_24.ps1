. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
$t = Find-BssidForSsidBand -Ssid 'Wifi1' -Band '2.4'
if ($t) { $t | Format-List } else { Write-Host 'no 2.4 bssid' }
Write-Host "Channel: $(Get-WifiUplinkChannel)"
