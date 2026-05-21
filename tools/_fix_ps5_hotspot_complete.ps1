# Full fix: Ethernet internet + PS5 on hotspot (Realtek USB — never disable Wi-Fi adapter).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_fix_ps5_hotspot_complete.log'
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
L "=== PS5 hotspot complete fix $(Get-Date -Format o) ==="

# 1) ZubCut attack blocks
$n = 0
$rulesOut = netsh advfirewall firewall show rule name=all verbose 2>$null | Out-String
foreach ($line in ($rulesOut -split "`r?`n")) {
    if ($line -match '^\s*Rule Name:\s+(zubcut_(?:ip_|block_|port_).+)') {
        netsh advfirewall firewall delete rule name="$($Matches[1].Trim())" 2>$null | Out-Null
        $n++
    }
}
L "Removed $n ZubCut block rule(s)"

Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name IPEnableRouter -Value 1 -Type DWord -Force

# 2) Wi-Fi adapter ON but disconnected from router (disabling kills hotspot on USB dongle)
$wifi = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Wireless LAN|802\.11|Wi-Fi' -and
    $_.InterfaceDescription -notmatch 'Direct|Hosted|Virtual'
} | Select-Object -First 1
if ($wifi) {
    if ($wifi.Status -eq 'Disabled') {
        L "Enabling Wi-Fi adapter $($wifi.Name) (required for hotspot radio)..."
        Enable-NetAdapter -Name $wifi.Name -Confirm:$false -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 4
    }
    $wlanOut = netsh wlan show interfaces 2>$null | Out-String
    if ($wlanOut -match 'State\s*:\s*connected') {
        L "Disconnecting PC from router Wi-Fi (hotspot stays on same radio)..."
        netsh wlan disconnect interface="$($wifi.Name)" 2>$null | Out-Null
        Start-Sleep -Seconds 3
    }
    Set-NetIPInterface -InterfaceIndex $wifi.ifIndex -AddressFamily IPv4 -InterfaceMetric 8000 -ErrorAction SilentlyContinue
    L "Wi-Fi $($wifi.Name): enabled, not router client, low route metric"
}

# 3) Ethernet preferred for internet
$eth = Get-EthernetUplinkAdapter
if (-not $eth) {
    L 'ERROR: Plug Ethernet to router first.'
    exit 2
}
Set-NetIPInterface -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -InterfaceMetric 10 -ErrorAction SilentlyContinue
Set-NetConnectionProfile -InterfaceIndex $eth.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue
L "Internet uplink: $($eth.Name)"

# 4) Hotspot on + IPv6 off on hotspot NIC only
foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc')) {
    Start-Service $svc -ErrorAction SilentlyContinue
}
Set-HotspotDhcpRegistry
Ensure-HotspotDhcpFirewall

if (-not (Test-MobileHotspotGateway)) {
    L 'Starting Mobile Hotspot...'
    $mgr = Get-TetheringManager
    if ($mgr) {
        $null = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'Start' 60
        Start-Sleep -Seconds 10
    }
}
if (-not (Test-MobileHotspotGateway)) {
    L 'ERROR: Turn Mobile Hotspot ON in Settings, run this again.'
    exit 3
}

$ap = Get-HotspotPrivateAdapter
if ($ap) {
    Set-NetConnectionProfile -InterfaceIndex $ap.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue
    try { Disable-NetAdapterBinding -Name $ap.Name -ComponentID ms_tcpip6 -ErrorAction SilentlyContinue } catch {}
    L "Hotspot NIC: $($ap.Name)"
}

# 5) ICS Ethernet -> hotspot (only touch this pair)
Enable-EthernetHotspotIcs -Quiet | Out-Null
Start-Sleep -Seconds 2
if (-not (Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)) {
    L 'Re-applying ICS...'
    Enable-EthernetHotspotIcs -Quiet | Out-Null
    Start-Sleep -Seconds 3
}

# 6) NAT firewall for hotspot clients
foreach ($r in @(
    @{ N = 'ZubCut-Hotspot-NAT-In'; D = 'in' },
    @{ N = 'ZubCut-Hotspot-NAT-Out'; D = 'out' }
)) {
    netsh advfirewall firewall delete rule name="$($r.N)" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="$($r.N)" dir=$($r.D) action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
}

L ''
L '=== RESULT ==='
$s = Test-Ps5HotspotReady
L "  Gateway: $($s.Gateway)  DHCP: $($s.Dhcp)  ICS: $($s.IcsSharing)  Ready: $($s.Ready)"
L '  Routes:'
Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 3 | ForEach-Object {
        $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
        L ("    $($a.Name) metric=$($_.RouteMetric)/$($_.InterfaceMetric)")
    }
L '  Sharing:'
$share = New-Object -ComObject HNetCfg.HNetShare
foreach ($conn in @($share.EnumEveryConnection())) {
    try {
        $p = $share.NetConnectionProps($conn)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        if ($cfg.SharingEnabled) {
            $st = [int]$cfg.SharingConnectionType
            $role = if ($st -eq 0) { 'PUBLIC' } else { 'PRIVATE' }
            L "    $($p.Name) $role"
        }
    } catch {}
}
try {
    $mgr = Get-TetheringManager
    if ($mgr) { L "  Hotspot: $($mgr.TetheringOperationalState) $(Get-MobileHotspotApBandLabel $mgr)" }
} catch {}

L ''
if ($s.Ready) {
    L 'PC is ready. On PS5:'
    L '  - Stay on osps (do not disable PC Wi-Fi adapter)'
    L '  - DNS Manual: 8.8.8.8 and 1.1.1.1'
    L '  - ZubCut Kill/Dupe OFF'
    L '  - Test Internet Connection'
} else {
    L 'Still not ready - toggle hotspot OFF 15 sec ON in Settings, run again.'
}
L "Log: $log"
exit $(if ($s.Ready) { 0 } else { 1 })
