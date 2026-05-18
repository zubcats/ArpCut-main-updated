# PS5 on hotspot: connected but no internet — ICS route + purge ZubCut blocks + NAT helpers.
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_ps5_internet_fix_log.txt'
function L($m) { Write-Host $m; Add-Content $log $m -Encoding utf8 -ErrorAction SilentlyContinue }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    L 'Click Yes on UAC...'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

'' | Set-Content $log -Force
L "=== PS5 hotspot internet fix $(Get-Date -Format o) ==="

# Kill/Dupe IP blocks on 192.168.137.x stop PS5 internet even when ICS is correct.
$removed = 0
$rulesOut = netsh advfirewall firewall show rule name=all verbose 2>$null | Out-String
foreach ($line in ($rulesOut -split "`r?`n")) {
    if ($line -match '^\s*Rule Name:\s+(zubcut_(?:ip_|block_|port_).+)') {
        $n = $Matches[1].Trim()
        netsh advfirewall firewall delete rule name="$n" 2>$null | Out-Null
        L "Removed block rule: $n"
        $removed++
    }
}
L "Removed $removed ZubCut block rule(s)"

try {
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name IPEnableRouter -Value 1 -Type DWord -Force
    L 'IPEnableRouter=1'
} catch {}

foreach ($r in @(
    @{ N = 'ZubCut-Hotspot-LAN-In'; D = 'in'; Rip = '192.168.137.0/24' },
    @{ N = 'ZubCut-Hotspot-LAN-Out'; D = 'out'; Rip = '192.168.137.0/24' }
)) {
    netsh advfirewall firewall delete rule name="$($r.N)" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="$($r.N)" dir=$($r.D) action=allow remoteip=$($r.Rip) enable=yes | Out-Null
}
Ensure-HotspotDhcpFirewall
L 'Firewall: allow hotspot LAN + DHCP'

if (-not (Test-EthernetInternetUplink)) {
    L 'FAILED: Ethernet must be connected to your router (PC internet on cable).'
    exit 2
}

Disconnect-WifiClientForEthernetHotspot | Out-Null
Ensure-EthernetPreferredRouting | Out-Null
L 'Wi-Fi client disconnected (if any); Ethernet preferred for default route'

if (-not (Test-MobileHotspotGateway)) {
    L 'Hotspot off — starting...'
    Ensure-MobileHotspotOnRobust | Out-Null
}
if (-not (Test-MobileHotspotGateway)) {
    L 'FAILED: Turn Mobile hotspot ON in Settings first.'
    exit 3
}

$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
foreach ($a in @($eth, $ap)) {
    if ($a) {
        try { Set-NetConnectionProfile -InterfaceIndex $a.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue } catch {}
    }
}

if (-not (Enable-EthernetHotspotIcs -Quiet)) {
    L 'ICS auto-enable failed — check Ethernet Properties -> Sharing -> hotspot adapter'
    exit 4
}
L 'ICS re-applied: Ethernet -> hotspot'

# Wait for DHCP (SharedAccess) without restarting icssvc (drops clients).
$dhcpOk = $false
for ($i = 0; $i -lt 12; $i++) {
    if (Test-HotspotDhcpListening) { $dhcpOk = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $dhcpOk) {
    L 'DHCP not up — restarting SharedAccess only (hotspot stays on)...'
    Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
}

L ''
L '=== STATUS ==='
$s = Test-Ps5HotspotReady
L "  Gateway: $($s.Gateway)  DHCP: $($s.Dhcp)  ICS: $($s.IcsSharing)  Ready: $($s.Ready)"

L '--- ARP (PS5 should show 192.168.137.x, not only .255) ---'
$arpLines = @(arp -a | Select-String '192\.168\.137\.\d+' | Where-Object { $_.Line -notmatch '\.255\s' })
if ($arpLines.Count -eq 0) {
    L '  (no PS5 yet — on PS5: forget osps, reconnect, wait 30 sec)'
} else {
    $arpLines | ForEach-Object { L ('  ' + $_.Line.Trim()) }
}

try {
    $mgr = Get-TetheringManager
    if ($mgr) {
        L "Hotspot: $($mgr.TetheringOperationalState) band=$(Get-MobileHotspotApBandLabel $mgr)"
        foreach ($c in $mgr.GetTetheringClients()) {
            L "  Tether client: $($c.MacAddress) $($c.HostName)"
        }
    }
} catch {}

L ''
L 'On PS5:'
L '  1. Settings -> Network -> Connection Status -> IP must be 192.168.137.x (not 0.0.0.0)'
L '  2. If IP is OK but internet fails: DNS Manual -> 8.8.8.8 and 1.1.1.1'
L '  3. Turn OFF ZubCut Kill/Dupe on this PS5 while testing'
L '  4. If still fails: forget network osps, reconnect, run this script again'
L ''
if ($s.Ready) {
    L 'SUCCESS: PC side ready. Test PS5 internet now.'
    exit 0
}
if ($s.IcsSharing -and $s.Gateway) {
    L 'PARTIAL: ICS OK — toggle hotspot OFF 15 sec ON, reconnect PS5'
    exit 1
}
L 'FAILED: Run Repair PS5 Hotspot (Ethernet) from desktop, then this script again'
exit 2
