# Allow PS5 on hotspot: firewall + verify DHCP/NAT (run as Administrator).
$ErrorActionPreference = 'Continue'
Write-Host '=== Fix hotspot for PS5 clients ==='

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator'
    Read-Host 'Press Enter'
    exit 1
}

# Allow DHCP and hotspot subnet through firewall.
$rules = @(
    @{ Name = 'ZubCut-DHCP-In'; Dir = 'in'; Proto = 'UDP'; Port = 67 },
    @{ Name = 'ZubCut-DHCP-Out'; Dir = 'out'; Proto = 'UDP'; Port = 67 },
    @{ Name = 'ZubCut-DHCPClient-In'; Dir = 'in'; Proto = 'UDP'; Port = 68 },
    @{ Name = 'ZubCut-DHCPClient-Out'; Dir = 'out'; Proto = 'UDP'; Port = 68 }
)
foreach ($r in $rules) {
    netsh advfirewall firewall delete rule name="$($r.Name)" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="$($r.Name)" dir=$($r.Dir) action=allow protocol=$($r.Proto) localport=$($r.Port) enable=yes | Out-Null
    Write-Host "Firewall allow: $($r.Name)"
}
netsh advfirewall firewall delete rule name="ZubCut-Hotspot-Subnet-In" 2>$null | Out-Null
netsh advfirewall firewall add rule name="ZubCut-Hotspot-Subnet-In" dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
netsh advfirewall firewall add rule name="ZubCut-Hotspot-Subnet-Out" dir=out action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null
Write-Host 'Firewall allow: 192.168.137.0/24'

foreach ($svc in @('SharedAccess', 'icssvc', 'Dhcp', 'WlanSvc')) {
    try { Restart-Service $svc -Force -ErrorAction SilentlyContinue } catch {}
}
Start-Sleep -Seconds 5

$dhcp = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
$gw = Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' }
Write-Host "dhcp67=$([bool]$dhcp) gw137=$([bool]$gw)"

Write-Host "`n--- ICS (must show Wi-Fi shared) ---"
try {
    $share = New-Object -ComObject HNetCfg.HNetShare
    $found = $false
    foreach ($conn in @($share.EnumEveryConnection())) {
        $p = $share.NetConnectionProps($conn)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        if ($cfg.SharingEnabled) {
            Write-Host "  ICS ON: $($p.Name) sharingType=$($cfg.SharingType)"
            $found = $true
        }
    }
    if (-not $found) { Write-Host '  WARNING: No ICS sharing - redo Wi-Fi Sharing tab!' }
} catch { Write-Host "  ICS check: $($_.Exception.Message)" }

Write-Host @"

=== On PS5 (if still fails to get IP automatically) ===
  Settings -> Network -> osps -> Advanced:
    IP: Manual
    Address: 192.168.137.2
    Subnet: 255.255.255.0
    Gateway: 192.168.137.1
    DNS: 8.8.8.8

Then: Mobile hotspot OFF 15 sec ON, reconnect PS5.
Watch here for PS5 in ARP:
"@

Read-Host 'Connect PS5 now, then press Enter'
$hotspotIf = Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1
if ($hotspotIf) {
    Get-NetNeighbor -InterfaceIndex $hotspotIf.InterfaceIndex -AddressFamily IPv4 -EA SilentlyContinue |
        Where-Object { $_.IPAddress -like '192.168.137.*' -and $_.IPAddress -ne '192.168.137.1' } |
        Format-Table IPAddress, LinkLayerAddress, State
}
try {
    $p = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    $m = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($p)
    Write-Host "Hotspot clients connected: $($m.ClientCount)"
} catch {}

Read-Host 'Press Enter to close'
