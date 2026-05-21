# PS5 has IP but no internet — NAT/routes only (no HNetCfg / no Sharing reset).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_fix_ps5_nat_light.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

'' | Set-Content $log -Force
L "=== PS5 NAT light fix $(Get-Date -Format o) ==="

Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name IPEnableRouter -Value 1 -Type DWord -Force
L 'IPEnableRouter=1'

Disconnect-WifiClientForEthernetHotspot | Out-Null
$eth = Get-EthernetUplinkAdapter
if ($eth) {
    Set-NetIPInterface -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -InterfaceMetric 10 -EA SilentlyContinue
    Set-NetConnectionProfile -InterfaceIndex $eth.ifIndex -NetworkCategory Private -EA SilentlyContinue
    L "Ethernet: $($eth.Name) metric 10, Private"
}
$ap = Get-HotspotPrivateAdapter
if ($ap) {
    Set-NetConnectionProfile -InterfaceIndex $ap.ifIndex -NetworkCategory Private -EA SilentlyContinue
    L "Hotspot: $($ap.Name)"
}

# Do NOT reset ICS via COM — user set Sharing manually
Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
Ensure-HotspotDhcpFirewall
foreach ($r in @('ZubCut-Hotspot-NAT-In', 'ZubCut-Hotspot-NAT-Out', 'ZubCut-Hotspot-LAN-In', 'ZubCut-Hotspot-LAN-Out')) {
    netsh advfirewall firewall delete rule name=$r 2>$null | Out-Null
}
netsh advfirewall firewall add rule name=ZubCut-Hotspot-NAT-In dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-NAT-Out dir=out action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-LAN-In dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-LAN-Out dir=out action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
L 'Firewall: hotspot NAT/LAN allow'

L 'Default routes:'
Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -EA SilentlyContinue |
    Sort-Object RouteMetric | ForEach-Object {
        $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
        L "  $($a.Name) -> $($_.NextHop) metric $($_.RouteMetric)"
    }

L ''
L 'VERIFY Ethernet 2 -> Sharing -> home network = Local Area Connection* 12'
L 'PS5 manual: IP 192.168.137.2  mask 255.255.255.0  GW 192.168.137.1  DNS 8.8.8.8'
L 'Then test again. Close ZubCut Kill/Dupe if open.'
