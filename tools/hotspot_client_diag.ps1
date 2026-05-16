$ErrorActionPreference = 'Continue'
Write-Host '=== Hotspot client / DHCP / NAT diag ==='

Write-Host "`n--- Adapters ---"
Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -or $_.InterfaceDescription -match 'Wi-Fi|Direct|Ethernet' } |
    Format-Table Name, Status, LinkSpeed, InterfaceDescription -AutoSize

Write-Host "--- IPv4 ---"
Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' } |
    ForEach-Object {
        $if = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
        "$($if.Name)  $($_.IPAddress)/$($_.PrefixLength)"
    }

Write-Host "`n--- DHCP port 67 ---"
Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue | Format-Table LocalAddress, OwningProcess

Write-Host "`n--- ARP (devices on LAN) ---"
$hotspotIf = Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1
if ($hotspotIf) {
    $idx = $hotspotIf.InterfaceIndex
    Get-NetNeighbor -InterfaceIndex $idx -AddressFamily IPv4 -EA SilentlyContinue |
        Where-Object { $_.State -ne 'Unreachable' -and $_.IPAddress -notlike '224.*' } |
        Format-Table IPAddress, LinkLayerAddress, State
} else {
    Write-Host 'No 192.168.137.1 gateway on PC'
}

Write-Host "`n--- Default route ---"
Get-NetRoute -DestinationPrefix '0.0.0.0/0' -EA SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 3 |
    ForEach-Object {
        $if = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
        "$($if.Name) -> $($_.NextHop)"
    }

Write-Host "`n--- ICS sharing ---"
try {
    $share = New-Object -ComObject HNetCfg.HNetShare
    foreach ($conn in @($share.EnumEveryConnection())) {
        $p = $share.NetConnectionProps($conn)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        if ($cfg.SharingEnabled) {
            Write-Host "ICS ON: $($p.Name) type=$($cfg.SharingType)"
        }
    }
} catch { Write-Host "ICS: $($_.Exception.Message) (run as admin for full ICS list)" }

Write-Host "`n--- Tethering clients ---"
try {
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $p = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if ($p) {
        $m = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($p)
        Write-Host "State=$($m.TetheringOperationalState) Clients=$($m.ClientCount)/$($m.MaxClientCount) Band=$($m.Configuration.Band)"
    }
} catch {}

Write-Host "`n--- Firewall profiles ---"
Get-NetFirewallProfile | Format-Table Name, Enabled

Write-Host "`n--- Block rules mentioning 192.168.137 ---"
Get-NetFirewallRule -EA SilentlyContinue | Where-Object { $_.Enabled -eq 'True' -and $_.Action -eq 'Block' } |
    Select-Object -First 20 DisplayName, Direction | Format-Table
