$log = Join-Path $PSScriptRoot '_hotspot_full_diag.txt'
'' | Set-Content $log -Encoding UTF8
function L([string]$m) { $m | Add-Content $log -Encoding UTF8; Write-Host $m }

L '=== SERVICES ==='
foreach ($n in @('SharedAccess','icssvc','WlanSvc','Dhcp','mpssvc','BFE')) {
    $s = Get-Service $n -ErrorAction SilentlyContinue
    if ($s) { L "$($s.Name) $($s.Status) $($s.StartType)" } else { L "$n (missing)" }
}

L "`n=== ADAPTERS ==="
Get-NetAdapter | Where-Object {
    $_.InterfaceDescription -match 'Wi-Fi|Wireless|Direct|Hotspot|Ethernet' -or $_.Name -match 'Wi-Fi|Direct|Hotspot|Ethernet|Local'
} | ForEach-Object {
    L "$($_.Name) | $($_.Status) | $($_.InterfaceDescription)"
}

L "`n=== IPv4 ADDRESSES ==="
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' } |
    ForEach-Object {
        $if = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
        L "$($if.Name) -> $($_.IPAddress)/$($_.PrefixLength)"
    }

L "`n=== DHCP UDP 67 / 68 ==="
Get-NetUDPEndpoint -LocalPort 67,68 -ErrorAction SilentlyContinue |
    ForEach-Object { L "listen $($_.LocalAddress):$($_.LocalPort) pid=$($_.OwningProcess)" }
if (-not (Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue)) { L 'NO DHCP listener on port 67' }

L "`n=== DEFAULT ROUTE ==="
Get-NetRoute -DestinationPrefix '0.0.0.0/0' -EA SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 3 |
    ForEach-Object {
        $if = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
        L "$($if.Name) via $($_.NextHop) metric=$($_.RouteMetric)"
    }

L "`n=== ICS SHARING (needs admin) ==="
try {
    $share = New-Object -ComObject HNetCfg.HNetShare
    $any = $false
    foreach ($conn in @($share.EnumEveryConnection())) {
        $p = $share.NetConnectionProps($conn)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        if ($cfg.SharingEnabled) {
            $any = $true
            L "ICS ON: $($p.Name) type=$($cfg.SharingType)"
        }
    }
    if (-not $any) { L 'ICS sharing: none enabled' }
} catch { L "ICS query failed: $($_.Exception.Message)" }

L "`n=== FIREWALL (private) DHCP rules ==="
Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object {
    $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block'
} | Select-Object -First 15 DisplayName | ForEach-Object { L "BLOCK IN: $($_.DisplayName)" }

L "`n=== TETHERING API ==="
try {
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if ($profile) {
        $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
        L "TetheringOperationalState=$($mgr.TetheringOperationalState)"
        L "MaxClients=$($mgr.MaxClientCount) Clients=$($mgr.ClientCount)"
        L "SSID=$($mgr.Configuration.SsidPrefix) Band=$($mgr.Configuration.Band)"
    } else { L 'No internet connection profile' }
} catch { L "Tethering API: $($_.Exception.Message)" }

L "`n=== WLAN DRIVER (hosted network) ==="
netsh wlan show drivers 2>&1 | ForEach-Object { L $_ }

L "`n=== DONE ==="
