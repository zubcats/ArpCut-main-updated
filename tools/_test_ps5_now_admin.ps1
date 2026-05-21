$log = "c:\Users\caden\OneDrive\Documents\GitHub\ArpCut-main-updated\tools\_test_ps5_now_admin.log"
function L($m) { $m | Tee-Object -FilePath $log -Append }
'' | Set-Content $log
. "c:\Users\caden\OneDrive\Documents\GitHub\ArpCut-main-updated\tools\_hotspot_2ghz_apply.ps1"

L "=== Admin PS5 test $(Get-Date -Format o) ==="
$ap = Get-HotspotPrivateAdapter
$eth = Get-EthernetUplinkAdapter

foreach ($c in (Get-TetheringManager).GetTetheringClients()) {
    L "CLIENT $($c.MacAddress) $($c.HostName)"
}

Set-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters -Name IPEnableRouter -Value 1 -Type DWord -Force
Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
Ensure-HotspotDhcpFirewall
netsh advfirewall firewall add rule name=ZubCut-Hotspot-Full-In dir=in action=allow remoteip=192.168.137.0/24 enable=yes profile=any 2>$null | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-Full-Out dir=out action=allow remoteip=192.168.137.0/24 enable=yes profile=any 2>$null | Out-Null

$pcMac = ($ap.MacAddress -replace '-',':').ToUpper()
foreach ($last in 2..32) {
    $ip = "192.168.137.$last"
    ping -n 2 -w 300 $ip | Out-Null
}
Start-Sleep 2

$targets = @(2..32 | ForEach-Object { "192.168.137.$_" })
foreach ($ip in $targets) {
    $n = Get-NetNeighbor -IPAddress $ip -EA SilentlyContinue
    if ($n -and $n.LinkLayerAddress -ne '00-00-00-00-00-00' -and $n.State -ne 'Unreachable') {
        L "LIVE $ip $($n.LinkLayerAddress) $($n.State)"
        $macDash = $n.LinkLayerAddress
        arp -s $ip $macDash 2>$null | Out-Null
    }
}

$py = "from scapy.all import ARP,Ether,sendp; pc='$pcMac'; gw='192.168.137.1'
for ip in [2,31,32]:
  p=f'192.168.137.{ip}'
  for _ in range(5):
    sendp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(op=2,psrc=gw,hwsrc=pc,pdst=gw,hwdst='ff:ff:ff:ff:ff:ff'), verbose=0)
print('heal done')"
py -3 -c $py 2>&1 | ForEach-Object { L $_ }

L "ICS=$(Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)"
arp -a | Select-String '192.168.137' | Where-Object { $_ -notmatch '255|137\.1\s' } | ForEach-Object { L $_.Line.Trim() }
Get-NetNeighbor | Where-Object { $_.IPAddress -like '192.168.137.*' -and $_.State -eq 'Reachable' } | ForEach-Object {
    L "REACHABLE $($_.IPAddress) $($_.LinkLayerAddress)"
}
