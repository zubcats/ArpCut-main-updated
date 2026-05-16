$ErrorActionPreference = 'Continue'
Write-Host '=== Hotspot signal / broadcast diag ==='
Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Wi-Fi|Direct|Wireless' } |
    Format-Table Name, Status, LinkSpeed, InterfaceDescription -AutoSize

Write-Host "`n=== IPv4 ==="
Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' } |
    ForEach-Object {
        $if = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
        [PSCustomObject]@{ Adapter = $if.Name; IP = $_.IPAddress }
    } | Format-Table -AutoSize

Write-Host '=== DHCP 67 ==='
Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue | Format-Table LocalAddress, OwningProcess

try {
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $p = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if ($p) {
        $m = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($p)
        Write-Host "`n=== Mobile Hotspot API ==="
        Write-Host "State: $($m.TetheringOperationalState)"
        Write-Host "SSID prefix: $($m.Configuration.SsidPrefix)"
        Write-Host "Passphrase length: $($m.Configuration.Passphrase.Length)"
        Write-Host "Band: $($m.Configuration.Band)"
        Write-Host "Max clients: $($m.MaxClientCount)  Connected: $($m.ClientCount)"
    }
} catch { Write-Host "Tethering API: $($_.Exception.Message)" }

Write-Host "`n=== Wi-Fi radio (netsh) ==="
netsh wlan show interfaces 2>&1
Write-Host "`n=== Hosted network ==="
netsh wlan show hostednetwork 2>&1
