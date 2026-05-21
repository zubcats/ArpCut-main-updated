$log = Join-Path $PSScriptRoot '_diag_hotspot_last.txt'
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
$s = Show-Ps5HotspotStatus
@(
    "Gateway=$($s.Gateway)",
    "Hotspot=$($s.HotspotAdapter)",
    "Ethernet=$($s.Ethernet)",
    "DHCP=$($s.Dhcp)",
    "ICS=$($s.IcsSharing)",
    "Ready=$($s.Ready)"
) | Set-Content $log -Encoding UTF8
