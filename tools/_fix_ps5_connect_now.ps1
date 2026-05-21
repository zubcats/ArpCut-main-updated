# PS5 on hotspot: Wi-Fi OK but no IP/internet — IPv4-only + ICS + DHCP refresh (Ethernet uplink).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_fix_ps5_connect_log.txt'
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
. (Join-Path $PSScriptRoot '_winrt_await.ps1')

'' | Set-Content $log -Force
L "=== PS5 connect fix $(Get-Date -Format o) ==="

# Hotspot password must be set (empty passphrase breaks some clients)
$mgr = Get-TetheringManager
if ($mgr) {
    try {
        $cfg = $mgr.GetCurrentAccessPointConfiguration()
        $passLen = 0
        try { $passLen = [string]$cfg.Passphrase }.Length } catch {}
        L "Hotspot SSID=$($cfg.Ssid) Band=$($cfg.Band) PassphraseLen=$passLen"
        if ($passLen -lt 8) {
            L 'WARN: Hotspot password missing/short — set one in Settings -> Mobile hotspot (min 8 chars)'
        }
    } catch {
        L "Hotspot config: $($_.Exception.Message)"
    }
}

$ap = Get-HotspotPrivateAdapter
if (-not $ap) {
    L 'No hotspot adapter — turn Mobile hotspot ON in Settings'
    exit 2
}
L "Hotspot NIC: $($ap.Name) ifIndex=$($ap.ifIndex)"

# IPv6 off on hotspot only (PS5 stuck without IPv4 lease)
try {
    Disable-NetAdapterBinding -Name $ap.Name -ComponentID ms_tcpip6 -ErrorAction SilentlyContinue
    L 'Disabled IPv6 binding on hotspot adapter'
} catch {}
Set-NetIPInterface -InterfaceIndex $ap.ifIndex -AddressFamily IPv6 -InterfaceMetric 9999 -ErrorAction SilentlyContinue

if (-not (Get-NetIPAddress -InterfaceIndex $ap.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq '192.168.137.1' })) {
    New-NetIPAddress -InterfaceIndex $ap.ifIndex -IPAddress 192.168.137.1 -PrefixLength 24 -ErrorAction SilentlyContinue | Out-Null
}
Set-HotspotDhcpRegistry
Ensure-HotspotDhcpFirewall

# Allow ping + all traffic on hotspot LAN (test from PS5 after manual IP)
foreach ($r in @(
    @{ N = 'ZubCut-Hotspot-Ping-In'; D = 'in'; Prot = 'ICMPv4' },
    @{ N = 'ZubCut-Hotspot-All-In'; D = 'in'; Prot = 'Any' }
)) {
    netsh advfirewall firewall delete rule name="$($r.N)" 2>$null | Out-Null
    if ($r.Prot -eq 'ICMPv4') {
        netsh advfirewall firewall add rule name="$($r.N)" dir=in action=allow protocol=ICMPv4 remoteip=192.168.137.0/24 enable=yes | Out-Null
    } else {
        netsh advfirewall firewall add rule name="$($r.N)" dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
        netsh advfirewall firewall add rule name="$($r.N)-Out" dir=out action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
    }
}

$eth = Get-EthernetUplinkAdapter
if ($eth) {
    Disconnect-WifiClientForEthernetHotspot | Out-Null
    Ensure-EthernetPreferredRouting | Out-Null
    L "Uplink: $($eth.Name)"
    Enable-EthernetHotspotIcs -Quiet | Out-Null
} else {
    L 'WARN: No Ethernet uplink'
}

# Refresh DHCP: hotspot cycle + SharedAccess
if ($mgr -and $mgr.TetheringOperationalState.ToString() -eq 'On') {
    $null = Wait-WinRtAsync ($mgr.StopTetheringAsync()) 'Stop' 45
    Start-Sleep -Seconds 15
}
Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
if ($mgr) {
    $null = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'Start' 60
    Start-Sleep -Seconds 15
}
Enable-EthernetHotspotIcs -Quiet | Out-Null

L ''
L '=== PC STATUS ==='
$s = Test-Ps5HotspotReady
L "  Gateway: $($s.Gateway)  DHCP: $($s.Dhcp)  ICS: $($s.IcsSharing)"
arp -a | Select-String '192\.168\.137' | ForEach-Object { L $_.Line.Trim() }

L ''
L '=== PS5: USE MANUAL IP (Realtek hotspot DHCP often fails) ==='
L '  Settings -> Network -> Set Up Internet Connection -> osps -> Advanced'
L '  IP Address Settings -> Manual -> IPv4'
L '    IP address:     192.168.137.2'
L '    Subnet mask:    255.255.255.0'
L '    Default gateway: 192.168.137.1'
L '    Primary DNS:    8.8.8.8'
L '    Secondary DNS:    1.1.1.1'
L '  Do NOT use Automatic until this works.'
L ''
L 'If manual IP still has no internet: use Ethernet cable PS5 -> spare PC port (not router).'
L "Log: $log"
