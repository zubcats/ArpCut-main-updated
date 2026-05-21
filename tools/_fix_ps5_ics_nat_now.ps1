# Fix PS5 "NAT failed" — enable ICS Ethernet 2 (public) -> hotspot (private). Targeted COM only.
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_fix_ps5_ics_nat_now.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    L 'Click Yes on UAC'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

'' | Set-Content $log -Force
L "=== PS5 ICS/NAT fix $(Get-Date -Format o) ==="
L 'Close Network Connections property windows first (avoids hang).'

Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name IPEnableRouter -Value 1 -Type DWord -Force
Disconnect-WifiClientForEthernetHotspot | Out-Null

$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
if (-not $eth -or -not $ap) {
    L 'ERROR: Need Ethernet 2 + hotspot (192.168.137.1). Turn Mobile hotspot ON.'
    exit 1
}
L "Pair: $($eth.Name) [internet] -> $($ap.Name) [PS5]"

if (Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap) {
    L 'ICS already correct on this pair.'
} else {
    L 'Enabling ICS (targeted — only these two adapters)...'
    $ok = Enable-EthernetHotspotIcs -Quiet
    L "ICS enable result: $ok"
}

Ensure-HotspotDhcpFirewall
foreach ($r in @('ZubCut-Hotspot-NAT-In', 'ZubCut-Hotspot-NAT-Out')) {
    netsh advfirewall firewall delete rule name=$r 2>$null | Out-Null
    netsh advfirewall firewall add rule name=$r dir=$(if($r -match 'In'){'in'}else{'out'}) action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
}

$s = Test-Ps5HotspotReady
L "Gateway: $($s.Gateway) DHCP: $($s.Dhcp) ICS: $($s.IcsSharing) Ready: $($s.Ready)"

L ''
L 'PS5 manual: 192.168.137.2 / 255.255.255.0 / GW 192.168.137.1 / DNS 8.8.8.8'
L 'NAT Type may show Failed or Type 3 on PC hotspot — online play can still work.'
L 'Test: PS5 browser or game, not only Sony NAT test.'
L 'If ICS=False above: Ethernet 2 Sharing -> home = Local Area Connection* 12'
