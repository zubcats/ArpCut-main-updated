$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_diag_ps5_connect.log'
function L($m) { $m | Out-File $log -Append -Encoding utf8; Write-Host $m }

'' | Set-Content $log -Encoding utf8
L "=== PS5 connect diag $(Get-Date -Format o) ==="

L '--- Adapters ---'
Get-NetAdapter | Format-Table Name, Status, LinkSpeed, InterfaceDescription -AutoSize | Out-String | ForEach-Object { L $_ }

L '--- Hotspot IP ---'
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -like '192.168.137.*' } |
    Format-Table InterfaceAlias, IPAddress, PrefixLength -AutoSize | Out-String | ForEach-Object { L $_ }

L '--- WinRT ---'
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile(
        [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile())
    L "State=$($mgr.TetheringOperationalState)"
    $cfg = $mgr.Configuration
    L "SSID=$($cfg.SsidPrefix) Band=$($cfg.Band) PassphraseLen=$($cfg.Passphrase.Length)"
    $ap = $mgr.GetCurrentAccessPointConfiguration()
    L "AP.Band=$($ap.Band) AP.SSID=$($ap.Ssid) Channel=$($ap.Channel)"
    try {
        $clients = $mgr.GetTetheringClients()
        L "Connected clients: $($clients.Count)"
        foreach ($c in $clients) { L "  $($c.MacAddress) $($c.HostName)" }
    } catch { L "Clients: $($_.Exception.Message)" }
} catch { L "WinRT: $($_.Exception.Message)" }

L '--- WLAN scan (is osps visible?) ---'
netsh wlan show networks mode=bssid 2>&1 | Out-String | ForEach-Object { L $_ }

L '--- Hosted / Wi-Fi Direct ---'
netsh wlan show drivers 2>&1 | Select-String -Pattern 'Hosted|Hotspot|band|Band|802' | ForEach-Object { L $_.Line }
netsh wlan show hostednetwork 2>&1 | Out-String | ForEach-Object { L $_ }

L '--- Firewall profiles ---'
Get-NetFirewallProfile | Format-Table Name, Enabled -AutoSize | Out-String | ForEach-Object { L $_ }
