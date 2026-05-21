$log = "c:\Users\caden\OneDrive\Documents\GitHub\ArpCut-main-updated\tools\_fix_ps5_mtu_l2.log"
function L($m) { $m | Tee-Object -FilePath $log -Append }
'' | Set-Content $log
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Get-Content $log
    exit
}
. "c:\Users\caden\OneDrive\Documents\GitHub\ArpCut-main-updated\tools\_hotspot_2ghz_apply.ps1"
L "=== MTU + L2 fix $(Get-Date -Format o) ==="
$ap = Get-HotspotPrivateAdapter
$ifIdx = $ap.ifIndex
netsh interface ipv4 set subinterface "$ifIdx" mtu=1400 store=persistent 2>&1 | ForEach-Object { L $_ }
netsh interface ipv4 set subinterface "$ifIdx" mtu=1400 store=active 2>&1 | ForEach-Object { L $_ }
L "MTU 1400 on $($ap.Name)"
Set-NetConnectionProfile -InterfaceIndex $ifIdx -NetworkCategory Private -EA SilentlyContinue
Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
Ensure-HotspotDhcpFirewall
$pcMac = ($ap.MacAddress -replace '-',':').ToUpper()
py -3 -c "from scapy.all import ARP,Ether,sendp; pc='$pcMac'; gw='192.168.137.1'; [sendp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(op=2,psrc=gw,hwsrc=pc,pdst=gw,hwdst='ff:ff:ff:ff:ff:ff'), verbose=0) for _ in range(12)]; print('ok')" 2>&1 | ForEach-Object { L $_ }
L 'Wait 20s with PS5 on osps...'
Start-Sleep 20
foreach ($c in (Get-TetheringManager).GetTetheringClients()) { L "CLIENT $($c.MacAddress)" }
Get-NetNeighbor -InterfaceIndex $ifIdx -EA SilentlyContinue |
    Where-Object { $_.State -eq 'Reachable' -and $_.IPAddress -like '192.168.137.*' } |
    ForEach-Object { L "REACHABLE $($_.IPAddress) $($_.LinkLayerAddress)" }
$inc = (Get-NetNeighbor -InterfaceIndex $ifIdx -EA SilentlyContinue | Where-Object { $_.State -eq 'Incomplete' -and $_.IPAddress -like '192.168.137.*' }).Count
L "Incomplete neighbors: $inc (lower is better; 0 + Reachable = fixed)"
