$ErrorActionPreference = 'Continue'
Write-Host '=== Hotspot diagnostic ==='
Get-NetAdapter | Format-Table Name,Status,ifIndex,InterfaceDescription -AutoSize
Write-Host ''
Write-Host 'IPv4 on hotspot-related adapters:'
Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Direct|Hosted' -or $_.Name -match 'Local Area Connection|Wi-Fi'
} | ForEach-Object {
    $a = $_
    Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |
        ForEach-Object { Write-Host "  $($a.Name): $($_.IPAddress)/$($_.PrefixLength)" }
}
Write-Host ''
Write-Host "DHCP67: $([bool](Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue))"
Write-Host ''
Write-Host 'IPv6 binding on hotspot adapters:'
Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Direct|Hosted' -or $_.Name -match 'Local Area Connection'
} | ForEach-Object {
    $b = Get-NetAdapterBinding -Name $_.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
    Write-Host "  $($_.Name): IPv6 enabled=$($b.Enabled)"
}
Write-Host ''
Write-Host 'ICS sharing state:'
$share = New-Object -ComObject HNetCfg.HNetShare
foreach ($conn in @($share.EnumEveryConnection())) {
    try {
        $p = $share.NetConnectionProps($conn)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        if ($cfg.SharingEnabled) {
            Write-Host "  $($p.Name): type=$($cfg.SharingConnectionType)"
        }
    } catch {}
}
Write-Host ''
Write-Host 'ARP clients on 192.168.137.x:'
arp -a | Select-String '192\.168\.137'
