$log = Join-Path $PSScriptRoot '_fix_ps5_l2.log'
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
L "=== Hotspot cycle + L2 wait $(Get-Date -Format o) ==="

$ap = Get-HotspotPrivateAdapter
Set-NetConnectionProfile -InterfaceIndex $ap.ifIndex -NetworkCategory Private -EA SilentlyContinue
netsh advfirewall firewall delete rule name=ZubCut-Hotspot-Full-In 2>$null | Out-Null
netsh advfirewall firewall delete rule name=ZubCut-Hotspot-Full-Out 2>$null | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-Full-In dir=in action=allow remoteip=192.168.137.0/24 enable=yes profile=any | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-Full-Out dir=out action=allow remoteip=192.168.137.0/24 enable=yes profile=any | Out-Null

$mgr = Get-TetheringManager
L "Stop hotspot..."
Stop-MobileHotspotIfOn | Out-Null
Start-Sleep -Seconds 12
Set-MobileHotspotBandRegistry2Ghz | Out-Null
$mgr = Get-TetheringManager
Configure-MobileHotspotAccessPoint2Ghz $mgr $false | Out-Null
L "Start hotspot 2.4..."
$null = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'Start' 60
Start-Sleep -Seconds 12

Remove-NetNeighbor -IPAddress 192.168.137.2 -Confirm:$false -EA SilentlyContinue
arp -d 192.168.137.2 2>$null | Out-Null

$pcMac = ($ap.MacAddress -replace '-', ':').ToUpper()
L "Hotspot MAC $pcMac"
$py = "from scapy.all import ARP,Ether,sendp; pc='$pcMac'; [sendp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(op=2,psrc='192.168.137.1',hwsrc=pc,pdst='192.168.137.1',hwdst='ff:ff:ff:ff:ff:ff'), verbose=0) for _ in range(10)]; print('bcast ok')"
py -3 -c $py 2>&1 | ForEach-Object { L $_ }

L 'Waiting 60s — keep PS5 on osps (Automatic IP)...'
$ok = $false
$clientIp = $null
1..20 | ForEach-Object {
    Start-Sleep 3
    try {
        $mgr2 = Get-TetheringManager
        foreach ($c in $mgr2.GetTetheringClients()) {
            L "  tether client: $($c.MacAddress) $($c.HostName)"
            $ok = $true
        }
    } catch {}
    2..32 | ForEach-Object { ping -n 1 -w 120 "192.168.137.$_" | Out-Null }
    $live = Get-NetNeighbor -InterfaceAlias $ap.Name -EA SilentlyContinue |
        Where-Object {
            $_.IPAddress -like '192.168.137.*' -and
            $_.IPAddress -notmatch '\.(1|255)$' -and
            $_.State -in @('Reachable', 'Stale', 'Delay', 'Probe')
        }
    foreach ($n in $live) {
        L "  neighbor $($n.IPAddress) $($n.LinkLayerAddress) $($n.State)"
        $clientIp = $n.IPAddress
        $ok = $true
    }
}
arp -a | Select-String '192\.168\.137\.\d+' | Where-Object { $_ -notmatch '\.255' } | ForEach-Object { L $_.Line.Trim() }
if ($ok -and $clientIp) {
    L "L2 OK at $clientIp — applying internet path..."
    & (Join-Path $PSScriptRoot '_fix_ps5_nat_light.ps1') 2>&1 | ForEach-Object { L $_ }
} elseif ($ok) {
    L 'L2 OK (client seen) — test PS5 internet'
} else {
    L 'L2 STILL BROKEN - Windows sees no device on osps (0 tether clients)'
}
