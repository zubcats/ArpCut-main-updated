# Full PS5 hotspot diagnosis — what is broken and why.
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_diag_ps5_hotspot_full.log'
function L($m) { Write-Host $m; Add-Content $log $m -Encoding utf8 }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

'' | Set-Content $log -Force
L "=== PS5 hotspot full diag $(Get-Date -Format o) admin=$isAdmin ==="

# --- Adapters ---
L ''
L '=== NETWORK ADAPTERS ==='
Get-NetAdapter | Sort-Object Status -Descending | ForEach-Object {
    L ("  [{0}] {1} | {2}" -f $_.Status, $_.Name, $_.InterfaceDescription)
}

# --- Default routes (dual route = common break) ---
L ''
L '=== DEFAULT ROUTES (internet) ==='
Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric, InterfaceMetric |
    ForEach-Object {
        $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
        $n = if ($a) { $a.Name } else { '?' }
        L ("  {0} via {1} metric={2}/{3}" -f $n, $_.NextHop, $_.RouteMetric, $_.InterfaceMetric)
    }

# --- Hotspot gateway ---
L ''
L '=== HOTSPOT (192.168.137.x) ==='
$gw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1
if ($gw) {
    L "  Gateway 192.168.137.1: YES on ifIndex $($gw.InterfaceIndex)"
} else {
    L '  Gateway 192.168.137.1: NO - Mobile Hotspot is off or has no IP'
}

$dhcp67 = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
if ($dhcp67) {
    L ("  DHCP listening UDP 67: YES on {0} pid={1}" -f $dhcp67.LocalAddress, $dhcp67.OwningProcess)
} else {
    L '  DHCP listening UDP 67: NO - PS5 cannot get IP (DHCP timeout)'
}

L '  ARP on 137.x (PS5 should appear as 192.168.137.x):'
$arpClients = @(arp -a | Select-String '192\.168\.137\.\d+' | Where-Object { $_.Line -notmatch '\.255\s' })
if ($arpClients.Count -eq 0) {
    L '    (none - PS5 not on LAN or no lease yet)'
} else {
    $arpClients | ForEach-Object { L ('    ' + $_.Line.Trim()) }
}

# --- ICS sharing (needs admin for COM) ---
L ''
L '=== INTERNET CONNECTION SHARING ==='
if (-not $isAdmin) {
    L '  (run as Administrator for ICS details)'
} else {
    . (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
    $eth = Get-EthernetUplinkAdapter
    $ap = Get-HotspotPrivateAdapter
    if ($eth) { L "  Internet uplink: $($eth.Name)" } else { L '  Internet uplink: NOT FOUND' }
    if ($ap) { L "  Hotspot adapter: $($ap.Name)" } else { L '  Hotspot adapter: NOT FOUND' }

    if ($eth -and $ap) {
        $icsOk = Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap
        L "  ICS Ethernet->hotspot: $icsOk"
        if (-not $icsOk) {
            L '  BROKEN: Sharing must be Ethernet (public) -> Wi-Fi Direct / Local Area Connection* (private)'
        }
    }

    $share = New-Object -ComObject HNetCfg.HNetShare
    L '  Adapters with sharing enabled:'
    $anyShare = $false
    foreach ($conn in @($share.EnumEveryConnection())) {
        try {
            $p = $share.NetConnectionProps($conn)
            $cfg = $share.INetSharingConfigurationForINetConnection($conn)
            if ($cfg.SharingEnabled) {
                $anyShare = $true
                $st = [int]$cfg.SharingConnectionType
                $role = if ($st -eq 0) { 'PUBLIC (internet)' } elseif ($st -eq 1) { 'PRIVATE (clients)' } else { "type=$st" }
                L "    $($p.Name) - $role"
            }
        } catch {}
    }
    if (-not $anyShare) {
        L '    (none) - BROKEN: no sharing enabled'
    }
}

# --- WinRT hotspot ---
L ''
L '=== MOBILE HOTSPOT (WinRT) ==='
try {
    . (Join-Path $PSScriptRoot '_winrt_await.ps1')
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile(
        [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile())
    if ($mgr) {
        L "  State: $($mgr.TetheringOperationalState)"
        $ap = $mgr.GetCurrentAccessPointConfiguration()
        L "  Band: $($ap.Band)  SSID: $($ap.Ssid)"
        foreach ($c in $mgr.GetTetheringClients()) {
            L "  Client: $($c.MacAddress) $($c.HostName)"
        }
    }
} catch {
    L "  WinRT error: $($_.Exception.Message)"
}

# --- Wi-Fi client (competes with hotspot on USB dongle) ---
L ''
L '=== PC WI-FI CLIENT (should be off when Ethernet is internet) ==='
$wlan = netsh wlan show interfaces 2>$null | Out-String
if ($wlan -match 'State\s*:\s*connected') {
    if ($wlan -match 'SSID\s*:\s*(.+)') { L "  BROKEN?: PC Wi-Fi still connected to: $($Matches[1].Trim())" }
    L '  This can break Ethernet->hotspot ICS on Realtek USB adapters'
} else {
    L '  PC Wi-Fi client: disconnected (good for Ethernet uplink)'
}

# --- ZubCut firewall blocks ---
L ''
L '=== ZUBCUT FIREWALL (blocks PS5 on 137.x) ==='
$zubcutBlock = @()
$zubcutAll = @()
$rulesOut = netsh advfirewall firewall show rule name=all verbose 2>$null | Out-String
foreach ($line in ($rulesOut -split "`r?`n")) {
    if ($line -match '^\s*Rule Name:\s+(zubcut.+)') {
        $n = $Matches[1].Trim()
        $zubcutAll += $n
        if ($n -match 'zubcut_(ip_|block_|port_)') { $zubcutBlock += $n }
    }
}
if ($zubcutBlock.Count -eq 0) {
    L '  No ZubCut IP block rules (good)'
} else {
    L "  BROKEN: $($zubcutBlock.Count) attack block rule(s):"
    $zubcutBlock | Select-Object -First 8 | ForEach-Object { L "    $_" }
}

# --- Block rules targeting 137.x ---
L ''
L '=== FIREWALL BLOCK on 192.168.137.x ==='
$block137 = @()
$cur = ''
foreach ($line in ($rulesOut -split "`r?`n")) {
    if ($line -match '^\s*Rule Name:\s+(.+)') { $cur = $Matches[1].Trim(); continue }
    if ($cur -and $line -match '192\.168\.137' -and $line -match 'Block') {
        $block137 += $cur
        $cur = ''
    }
}
if ($block137.Count -eq 0) {
    L '  No block rules on hotspot subnet (good)'
} else {
    L "  BROKEN: $($block137.Count) block rule(s) on 137.x"
    $block137 | Select-Object -First 5 | ForEach-Object { L "    $_" }
}

# --- Services ---
L ''
L '=== SERVICES ==='
foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc', 'Dhcp')) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s) { L ("  ${svc}: $($s.Status)") } else { L "  ${svc}: missing" }
}

# --- Verdict ---
L ''
L '=== VERDICT ==='
$issues = @()
if (-not $gw) { $issues += 'Hotspot off or no 192.168.137.1' }
if (-not $dhcp67) { $issues += 'DHCP not running (PS5 IP timeout)' }
if ($isAdmin) {
    . (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1') -ErrorAction SilentlyContinue
    $eth = Get-EthernetUplinkAdapter
    $ap = Get-HotspotPrivateAdapter
    if ($eth -and $ap -and -not (Test-EthernetHotspotIcsActive $eth $ap)) {
        $issues += 'ICS not set to Ethernet -> hotspot'
    }
}
if ($zubcutBlock.Count -gt 0) { $issues += 'ZubCut firewall blocking PS5' }
if ($wlan -match 'State\s*:\s*connected' -and $eth) { $issues += 'PC Wi-Fi client still connected' }
$routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue)
if ($routes.Count -gt 1) {
    $ifaces = $routes | ForEach-Object { (Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA 0).Name } | Where-Object { $_ }
    if (($ifaces | Select-Object -Unique).Count -gt 1) {
        $issues += 'Multiple default routes (Wi-Fi + Ethernet)'
    }
}
if ($arpClients.Count -eq 0 -and $gw) {
    $issues += 'No PS5 on hotspot subnet yet (not connected or wrong Wi-Fi)'
}

if ($issues.Count -eq 0) {
    L '  PC side looks OK. If PS5 still fails: forget osps, reconnect, check Connection Status for 192.168.137.x'
} else {
    foreach ($i in $issues) { L "  >> $i" }
}
L ''
L "Log: $log"
