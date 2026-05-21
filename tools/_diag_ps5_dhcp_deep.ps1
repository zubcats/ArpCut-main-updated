$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_ps5_dhcp_deep.log'
'' | Set-Content $log -Encoding utf8
function L($m) { $m | Tee-Object -FilePath $log -Append }

L "=== Deep DHCP diag $(Get-Date -Format o) ==="

L '--- ZubCut firewall blocks ---'
netsh advfirewall firewall show rule name=all 2>$null | Select-String -Pattern 'zubcut' | ForEach-Object { L $_.Line }

L '--- DHCP listeners ---'
Get-NetUDPEndpoint -LocalPort 67,68 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess |
    Format-Table -AutoSize | Out-String | ForEach-Object { L $_ }

L '--- SharedAccess / ICS registry ---'
$sa = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
if (Test-Path $sa) {
    Get-ItemProperty $sa -ErrorAction SilentlyContinue |
        Select-Object ScopeAddress, ScopeAddressBackup, StandaloneDhcpAddress, EnableRebootPersistConnection |
        Format-List | Out-String | ForEach-Object { L $_ }
}

L '--- Hotspot NIC IPs ---'
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceAlias -match 'Local Area|Direct|Wi-Fi' } |
    Format-Table InterfaceAlias, IPAddress, PrefixLength -AutoSize | Out-String | ForEach-Object { L $_ }

L '--- ICS sharing ---'
$share = New-Object -ComObject HNetCfg.HNetShare
foreach ($conn in @($share.EnumEveryConnection())) {
    try {
        $p = $share.NetConnectionProps($conn)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        if ($cfg.SharingEnabled) {
            L "$($p.Name) type=$($cfg.SharingConnectionType) enabled=$($cfg.SharingEnabled)"
        }
    } catch {}
}

L '--- ARP 192.168.137 ---'
arp -a | Select-String '192\.168\.137' | ForEach-Object { L $_.Line.Trim() }

L '--- Routes 137 ---'
Get-NetRoute -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.DestinationPrefix -like '192.168.137*' } |
    Format-Table DestinationPrefix, NextHop, InterfaceAlias -AutoSize | Out-String | ForEach-Object { L $_ }

L '--- Tethering ---'
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -EA SilentlyContinue
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile(
        [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile())
    L "State=$($mgr.TetheringOperationalState)"
    $ap = $mgr.GetCurrentAccessPointConfiguration()
    L "AP Band=$($ap.Band) SSID=$($ap.Ssid)"
    try {
        foreach ($c in $mgr.GetTetheringClients()) { L "Client: $($c.MacAddress) $($c.HostName)" }
    } catch { L 'No tethering clients' }
} catch { L "WinRT: $($_.Exception.Message)" }

L '--- WinDivert / ZubCut process ---'
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'python|zubcut|elmo' } |
    Select-Object ProcessName, Id | Format-Table -AutoSize | Out-String | ForEach-Object { L $_ }
