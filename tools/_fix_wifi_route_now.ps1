# Remove stale default route on disconnected Wi-Fi (Ethernet should win).
$wifi = Get-NetAdapter -Name 'Wi-Fi' -ErrorAction SilentlyContinue
if ($wifi -and $wifi.Status -ne 'Up') {
    Get-NetRoute -InterfaceIndex $wifi.ifIndex -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed default route on disconnected Wi-Fi (ifIndex $($wifi.ifIndex))"
}
Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
    Select-Object InterfaceAlias, NextHop, RouteMetric | Format-Table -AutoSize
