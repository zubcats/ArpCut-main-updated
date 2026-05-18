# Fix "connected but no IP" while devices stay on hotspot (minimal disconnect).
$log = Join-Path $PSScriptRoot '_fix_dhcp_live.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Get-Content $log
    exit
}
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
'' | Set-Content $log -Force
L "=== DHCP live fix $(Get-Date -Format o) ==="

$ap = Get-HotspotPrivateAdapter
$eth = Get-EthernetUplinkAdapter
if (-not $ap) { L 'ERROR: no hotspot adapter'; exit 1 }

Set-NetConnectionProfile -InterfaceIndex $ap.ifIndex -NetworkCategory Private -EA SilentlyContinue
Set-NetConnectionProfile -InterfaceIndex $eth.ifIndex -NetworkCategory Private -EA SilentlyContinue

# Ensure gateway IP
$gw = Get-NetIPAddress -InterfaceIndex $ap.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' }
if (-not $gw) {
    New-NetIPAddress -InterfaceIndex $ap.ifIndex -IPAddress 192.168.137.1 -PrefixLength 24 -EA Stop | Out-Null
    L 'Added 192.168.137.1'
}

Set-HotspotDhcpRegistry
Ensure-HotspotDhcpFirewall
foreach ($r in @(
    @{ N = 'ZubCut-DHCP-Broadcast-In'; D = 'in'; LP = '67'; RIP = '255.255.255.255/32' },
    @{ N = 'ZubCut-DHCP-Broadcast-Out'; D = 'out'; LP = '67'; RIP = '255.255.255.255/32' },
    @{ N = 'ZubCut-DHCPClient-Broadcast-In'; D = 'in'; LP = '68'; RIP = '255.255.255.255/32' }
)) {
    netsh advfirewall firewall delete rule name="$($r.N)" 2>$null | Out-Null
    $args = @('advfirewall', 'firewall', 'add', 'rule', "name=$($r.N)", "dir=$($r.D)", 'action=allow', 'protocol=UDP', 'enable=yes', 'profile=any')
    if ($r.LP) { $args += "localport=$($r.LP)" }
    if ($r.RIP) { $args += "remoteip=$($r.RIP)" }
    & netsh @args 2>$null | Out-Null
}
L 'DHCP firewall (incl. broadcast) applied'

# Clear stale neighbor garbage from failed attempts
Get-NetNeighbor -InterfaceIndex $ap.ifIndex -EA SilentlyContinue |
    Where-Object { $_.State -eq 'Unreachable' -or $_.LinkLayerAddress -eq '00-00-00-00-00-00' } |
    ForEach-Object { Remove-NetNeighbor -IPAddress $_.IPAddress -Confirm:$false -EA SilentlyContinue }

Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
if (-not (Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)) {
    Enable-EthernetHotspotIcs -Quiet | Out-Null
}
L "ICS=$(Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)"

# Do NOT Restart-Service SharedAccess while hotspot is on — it drops the AP.
$mgr = Get-TetheringManager
if ($mgr -and $mgr.TetheringOperationalState.ToString() -ne 'On') {
    L 'Hotspot off — starting...'
    Start-MobileHotspotAfter2GhzConfig | Out-Null
    Start-Sleep -Seconds 10
} else {
    L 'Hotspot on — refreshing DHCP via icssvc bounce (not SharedAccess)...'
    Restart-Service icssvc -Force -EA SilentlyContinue
    Start-Sleep -Seconds 5
    Start-Service SharedAccess -EA SilentlyContinue
    Start-Sleep -Seconds 3
}

$dhcp = Test-HotspotDhcpListening
L "DHCP67=$dhcp Gateway=$(Test-MobileHotspotGateway)"

$pcMac = ($ap.MacAddress -replace '-', ':').ToUpper()
py -3 -c "from scapy.all import ARP,Ether,sendp; pc='$pcMac'; gw='192.168.137.1'; [sendp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(op=2,psrc=gw,hwsrc=pc,pdst=gw,hwdst='ff:ff:ff:ff:ff:ff'), verbose=0) for _ in range(8)]; print('gateway ARP sent')" 2>&1 | ForEach-Object { L $_ }

try {
    $mgr = Get-TetheringManager
    foreach ($c in $mgr.GetTetheringClients()) { L "CLIENT $($c.MacAddress) $($c.HostName)" }
} catch {}

L ''
L 'On PS5/phone NOW:'
L '  1. Stay on ArpCutPS5'
L '  2. Set IP to Automatic (not manual)'
L '  3. Disconnect Wi-Fi 10 sec, reconnect'
L '  4. Wait 60 seconds for IP'
L ''
L 'SSID ArpCutPS5  password Connect12345'
