Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | ForEach-Object {
    $adapter = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Name = $adapter.Name
        Desc = $adapter.InterfaceDescription
        GW = $_.NextHop
        Metric = $_.RouteMetric
    }
} | Format-Table -AutoSize
Write-Host "Test-EthernetInternetUplink: $(. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1'); Test-EthernetInternetUplink)"
