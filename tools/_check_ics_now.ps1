# Quick ICS status — run as Administrator.
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_check_ics_now.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }
'' | Set-Content $log -Force
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
L '=== Internet Connection Sharing ==='
if ($eth) { L "Internet uplink: $($eth.Name)" } else { L 'Internet uplink: NOT FOUND' }
if ($ap) { L "Hotspot adapter: $($ap.Name)" } else { L 'Hotspot adapter: NOT FOUND' }
if ($eth -and $ap) {
    $ok = Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap
    L "ICS Ethernet -> hotspot: $ok"
}

$share = New-Object -ComObject HNetCfg.HNetShare
$any = $false
L 'Adapters with sharing enabled:'
foreach ($conn in @($share.EnumEveryConnection())) {
    try {
        $p = $share.NetConnectionProps($conn)
        $cfg = $share.INetSharingConfigurationForINetConnection($conn)
        if ($cfg.SharingEnabled) {
            $any = $true
            $st = [int]$cfg.SharingConnectionType
            $role = if ($st -eq 0) { 'PUBLIC (internet)' } elseif ($st -eq 1) { 'PRIVATE (clients)' } else { "type=$st" }
            L "  $($p.Name) - $role"
        }
    } catch {}
}
if (-not $any) { L '  (none)' }

try {
    . (Join-Path $PSScriptRoot '_winrt_await.ps1')
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction SilentlyContinue
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile(
        [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile())
    if ($mgr) {
        L "Mobile hotspot: $($mgr.TetheringOperationalState)"
        foreach ($c in $mgr.GetTetheringClients()) { L "  Client: $($c.MacAddress)" }
    }
} catch {}
