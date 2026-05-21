# Test + fix PS5 on osps after reconnect (Automatic IP).
$log = Join-Path $PSScriptRoot '_test_ps5_hotspot_now.log'
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
L "=== PS5 hotspot test $(Get-Date -Format o) ==="

$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
L "Uplink: $($eth.Name)  Hotspot: $($ap.Name)"
L "Gateway: $(Test-MobileHotspotGateway)  DHCP67: $(Test-HotspotDhcpListening)"
L "ICS: $(Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)"

$mgr = Get-TetheringManager
if ($mgr) {
    L "Hotspot: $($mgr.TetheringOperationalState) band=$(Get-MobileHotspotApBandLabel $mgr)"
    try {
        $apc = $mgr.GetCurrentAccessPointConfiguration()
        L "SSID: $($apc.Ssid)"
    } catch {
        try { L "SSID: $($mgr.GetCurrentAccessPointConfiguration().Ssid)" } catch {}
    }
    try {
        $n = 0
        foreach ($c in $mgr.GetTetheringClients()) {
            $n++
            L "TETHER CLIENT: $($c.MacAddress)  $($c.HostName)"
        }
        if ($n -eq 0) { L 'TETHER CLIENTS: 0' }
    } catch { L "Clients err: $_" }
}

L '--- Ping 137.2-32 + ARP ---'
2..32 | ForEach-Object { ping -n 1 -w 200 "192.168.137.$_" | Out-Null }
Start-Sleep 1
arp -a | Select-String '192\.168\.137\.' | Where-Object { $_ -notmatch '\.255|137\.1\s' } | ForEach-Object { L $_.Line.Trim() }
Get-NetNeighbor -InterfaceAlias $ap.Name -EA SilentlyContinue |
    Where-Object { $_.IPAddress -like '192.168.137.*' -and $_.IPAddress -notmatch '\.(1|255)$' } |
    ForEach-Object { L "Neighbor $($_.IPAddress) $($_.LinkLayerAddress) $($_.State)" }

$client = Get-NetNeighbor -InterfaceAlias $ap.Name -EA SilentlyContinue |
    Where-Object {
        $_.IPAddress -like '192.168.137.*' -and $_.IPAddress -notmatch '\.(1|255)$' -and
        $_.State -in @('Reachable', 'Stale', 'Delay', 'Probe') -and
        $_.LinkLayerAddress -ne '00-00-00-00-00-00'
    } | Select-Object -First 1

if ($client) {
    L "FOUND PS5 at $($client.IPAddress) MAC $($client.LinkLayerAddress)"
    & (Join-Path $PSScriptRoot '_fix_ps5_nat_light.ps1') 2>&1 | ForEach-Object { L $_ }
    $pingGw = Test-Connection 192.168.1.1 -Count 1 -Quiet -EA SilentlyContinue
    $pingPs5 = Test-Connection $client.IPAddress -Count 2 -Quiet -EA SilentlyContinue
    L "PC ping router: $pingGw  PC ping PS5: $pingPs5"
    L 'PS5 should have internet now - test PS Store not NAT test'
} else {
    L 'NO L2 client - Windows still does not see PS5 on osps'
    L 'Running hotspot refresh...'
    & (Join-Path $PSScriptRoot '_fix_ps5_internet_now.ps1') 2>&1 | Select-Object -Last 15 | ForEach-Object { L $_ }
}
