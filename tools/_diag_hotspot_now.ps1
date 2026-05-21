$ErrorActionPreference = 'Continue'
Write-Host '=== Adapters (Up) ==='
Get-NetAdapter | Where-Object Status -eq 'Up' | Format-Table Name, InterfaceDescription, LinkSpeed -AutoSize

Write-Host '=== Default route ==='
Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric | Select-Object -First 3 | ForEach-Object {
        $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
        [PSCustomObject]@{ Adapter = $a.Name; Desc = $a.InterfaceDescription; NextHop = $_.NextHop }
    } | Format-Table -AutoSize

Write-Host '=== Hotspot subnet ==='
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -like '192.168.137.*' } |
    Format-Table InterfaceAlias, IPAddress -AutoSize

Write-Host "=== DHCP listening (port 67): $([bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue)) ==="

Write-Host '=== Wi-Fi client ==='
netsh wlan show interfaces

Write-Host '=== ICS sharing ==='
$share = New-Object -ComObject HNetCfg.HNetShare
foreach ($conn in @($share.EnumEveryConnection())) {
    try {
        $p = $share.NetConnectionProps($conn)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        if ($cfg.SharingEnabled) {
            Write-Host "  $($p.Name) SharingType=$($cfg.SharingConnectionType)"
        }
    } catch {}
}

Write-Host '=== WinRT hotspot ==='
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
    Write-Host "  State=$($mgr.TetheringOperationalState)"
    $ap = $mgr.GetCurrentAccessPointConfiguration()
    Write-Host "  AP.Band=$($ap.Band) SSID=$($ap.Ssid)"
} catch {
    Write-Host "  WinRT error: $($_.Exception.Message)"
}

Write-Host '=== Services ==='
Get-Service SharedAccess, icssvc, WlanSvc, Dhcp | Format-Table Name, Status -AutoSize
