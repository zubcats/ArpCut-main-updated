# Fix PS5 on hotspot with manual IP — no user steps, full repair.
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_fix_ps5_internet_now.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Get-Content $log
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
. (Join-Path $PSScriptRoot '_winrt_await.ps1')

'' | Set-Content $log -Force
L "=== PS5 internet fix $(Get-Date -Format o) ==="

# Stop ZubCut attacks
Get-Process ZubCut -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
try {
    $src = Join-Path (Split-Path $PSScriptRoot -Parent) 'src'
    if (Test-Path $src) {
        $env:PYTHONPATH = $src
        py -3 -c "import sys; sys.path.insert(0, r'$src'); from tools.pfctl import teardown_all_zubcut_network_attacks; print(teardown_all_zubcut_network_attacks())" 2>&1 | ForEach-Object { L $_ }
    }
} catch { L "pfctl: $_" }

Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name IPEnableRouter -Value 1 -Type DWord -Force
netsh interface ipv4 set global forwarding=enabled 2>$null | Out-Null
L 'IP forwarding enabled'

Disconnect-WifiClientForEthernetHotspot | Out-Null
$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
if (-not $eth -or -not $ap) {
    L "ERROR missing eth=$($eth.Name) ap=$($ap.Name)"
    exit 1
}
L "Uplink: $($eth.Name) Hotspot: $($ap.Name)"

Set-NetIPInterface -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -InterfaceMetric 10 -EA SilentlyContinue
Set-NetConnectionProfile -InterfaceIndex $eth.ifIndex -NetworkCategory Private -EA SilentlyContinue
Set-NetConnectionProfile -InterfaceIndex $ap.ifIndex -NetworkCategory Private -EA SilentlyContinue

# Hotspot must be up with 137.1
if (-not (Test-MobileHotspotGateway)) {
    Set-MobileHotspotBandRegistry2Ghz | Out-Null
    Ensure-MobileHotspotOnRobust -Quiet | Out-Null
}
$v4 = Get-NetIPAddress -InterfaceIndex $ap.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' }
if (-not $v4) {
    New-NetIPAddress -InterfaceIndex $ap.ifIndex -IPAddress 192.168.137.1 -PrefixLength 24 -EA SilentlyContinue | Out-Null
    L 'Added 192.168.137.1 on hotspot NIC'
}
Disable-NetAdapterBinding -Name $ap.Name -ComponentID ms_tcpip6 -EA SilentlyContinue

# ICS: only fix if broken (targeted COM — not mass disable all adapters)
$icsOk = Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap
L "ICS before: $icsOk"
if (-not $icsOk) {
    L 'Applying ICS Ethernet -> hotspot...'
    $ok = Enable-EthernetHotspotIcs -Quiet
    L "ICS enable: $ok"
    Start-Sleep 3
    $icsOk = Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap
    L "ICS after: $icsOk"
}

Ensure-HotspotDhcpFirewall
foreach ($n in @('ZubCut-Hotspot-NAT-In', 'ZubCut-Hotspot-NAT-Out', 'ZubCut-Hotspot-LAN-In', 'ZubCut-Hotspot-LAN-Out')) {
    netsh advfirewall firewall delete rule name=$n 2>$null | Out-Null
}
netsh advfirewall firewall add rule name=ZubCut-Hotspot-NAT-In dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-NAT-Out dir=out action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-LAN-In dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-LAN-Out dir=out action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null

# DHCP if down
if (-not (Test-HotspotDhcpListening)) {
    Restart-Service SharedAccess -Force -EA SilentlyContinue
    Start-Sleep 5
}
L "DHCP67: $(Test-HotspotDhcpListening)"

# Find PS5 — manual IP usually .2
$ps5Ip = '192.168.137.2'
L "Pinging PS5 at $ps5Ip ..."
$ping = Test-Connection -ComputerName $ps5Ip -Count 2 -Quiet -ErrorAction SilentlyContinue
L "Ping $ps5Ip : $ping"
1..16 | ForEach-Object { ping -n 1 -w 200 "192.168.137.$_" | Out-Null }
Start-Sleep 1
L 'ARP:'
arp -a | Select-String '192\.168\.137' | ForEach-Object { L $_.Line.Trim() }

# Gratuitous ARP + heal via Python
$py = @"
import sys, subprocess, re
sys.path.insert(0, r'$(Join-Path (Split-Path $PSScriptRoot -Parent) 'src')')
from scapy.all import ARP, Ether, sendp
gw, ps5 = '192.168.137.1', '$ps5Ip'
out = subprocess.check_output('arp -a', text=True, errors='replace')
mac = None
for line in out.splitlines():
    if ps5 in line and 'incomplete' not in line.lower():
        m = re.search(r'([0-9A-Fa-f]{2}([-:])[0-9A-Fa-f]{2}\2){5}[0-9A-Fa-f]{2}', line)
        if m: mac = m.group(0).replace('-',':').upper(); break
pc = None
for line in out.splitlines():
    if gw in line:
        m = re.search(r'([0-9A-Fa-f]{2}([-:])[0-9A-Fa-f]{2}\2){5}[0-9A-Fa-f]{2}', line)
        if m: pc = m.group(0).replace('-',':').upper(); break
if not pc:
    import socket
    from tools.utils import get_default_iface, good_mac
    pc = good_mac(getattr(get_default_iface(), 'mac', None)) or 'E8:4E:06:AB:C4:28'
print('PC', pc, 'PS5', mac or 'not in ARP')
for _ in range(6):
    sendp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(op=2,psrc=gw,hwsrc=pc,pdst=gw,hwdst='ff:ff:ff:ff:ff:ff'), verbose=0)
if mac:
    for _ in range(5):
        sendp(Ether(dst=mac)/ARP(op=2,psrc=gw,hwsrc=pc,pdst=ps5,hwdst=mac), verbose=0)
print('ARP heal sent')
"@
try { py -3 -c $py 2>&1 | ForEach-Object { L $_ } } catch { L "scapy: $_" }

# Show ICS sharing names
try {
    $share = New-Object -ComObject HNetCfg.HNetShare
    foreach ($conn in @($share.EnumEveryConnection())) {
        $p = $share.NetConnectionProps($conn)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        if ($cfg.SharingEnabled) {
            $st = [int]$cfg.SharingConnectionType
            $k = if ($st -eq 0) { 'PUBLIC' } elseif ($st -eq 1) { 'PRIVATE' } else { $st }
            L "Sharing ON: $($p.Name) = $k"
        }
    }
} catch { L "ICS enum: $_" }

L ''
L "RESULT: ICS=$icsOk gw=$(Test-MobileHotspotGateway) dhcp=$(Test-HotspotDhcpListening) ping_ps5=$ping"
if (-not $ping) {
    L 'PC does not see PS5 at 192.168.137.2 — wrong IP on PS5 or not on osps Wi-Fi link.'
}
elseif (-not $icsOk) {
    L 'PS5 reachable but ICS pair wrong — home network must be Local Area Connection* 12 on Ethernet 2.'
} else {
    L 'Path should work — PS5 test PS Store / game not NAT test.'
}
