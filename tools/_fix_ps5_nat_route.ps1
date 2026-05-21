# PS5 has 192.168.137.x but no internet — fix NAT route (Ethernet only, not Wi-Fi).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_fix_ps5_nat_route.log'
function L($m) { Write-Host $m; Add-Content $log $m -Encoding utf8 }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

'' | Set-Content $log -Force
L "=== PS5 NAT route fix $(Get-Date -Format o) ==="

# Purge ZubCut blocks on hotspot subnet
$rulesOut = netsh advfirewall firewall show rule name=all verbose 2>$null | Out-String
foreach ($line in ($rulesOut -split "`r?`n")) {
    if ($line -match '^\s*Rule Name:\s+(zubcut_(?:ip_|block_|port_).+)') {
        netsh advfirewall firewall delete rule name="$($Matches[1].Trim())" 2>$null | Out-Null
    }
}

Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name IPEnableRouter -Value 1 -Type DWord -Force

# Disconnect PC Wi-Fi client — dual default route breaks ICS NAT for PS5
Disconnect-WifiClientForEthernetHotspot | Out-Null
$wifi = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Wireless LAN|802\.11' -and $_.Name -notmatch 'Direct|Hosted'
} | Select-Object -First 1
if ($wifi) {
    try { Set-NetIPInterface -InterfaceIndex $wifi.ifIndex -AddressFamily IPv4 -InterfaceMetric 8000 -ErrorAction Stop } catch {}
    L "Wi-Fi metric raised: $($wifi.Name)"
}

$eth = Get-EthernetUplinkAdapter
if ($eth) {
    Set-NetIPInterface -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -InterfaceMetric 10 -ErrorAction SilentlyContinue
    Set-NetConnectionProfile -InterfaceIndex $eth.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue
    L "Ethernet uplink: $($eth.Name) metric=10"
}

$ap = Get-HotspotPrivateAdapter
if ($ap) {
    Set-NetConnectionProfile -InterfaceIndex $ap.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue
}

Enable-EthernetHotspotIcs -Quiet | Out-Null
Ensure-HotspotDhcpFirewall

# Allow forwarded traffic on hotspot subnet
netsh advfirewall firewall delete rule name="ZubCut-Hotspot-NAT-In" 2>$null | Out-Null
netsh advfirewall firewall delete rule name="ZubCut-Hotspot-NAT-Out" 2>$null | Out-Null
netsh advfirewall firewall add rule name="ZubCut-Hotspot-NAT-In" dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name="ZubCut-Hotspot-NAT-Out" dir=out action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null

L ''
L 'Default routes now:'
Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric | ForEach-Object {
        $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
        L ("  $($a.Name) via $($_.NextHop) metric=$($_.RouteMetric)")
    }

$s = Test-Ps5HotspotReady
L ''
L "ICS: $($s.IcsSharing) Gateway: $($s.Gateway)"
arp -a | Select-String '192\.168\.137\.\d+' | Where-Object { $_.Line -notmatch '\.255' } | ForEach-Object { L $_.Line.Trim() }

L ''
L 'PS5: set DNS to Manual 8.8.8.8 and 1.1.1.1 (IP can be auto or 192.168.137.2)'
L 'Turn OFF ZubCut Kill/Dupe. Test internet on PS5.'
L "Log: $log"
