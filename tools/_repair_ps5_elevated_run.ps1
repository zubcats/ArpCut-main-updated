# Elevated one-shot: start hotspot + ICS (logged). Called by agent/automation.
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_repair_ps5_hotspot_last.log'
'' | Set-Content $log -Encoding UTF8
function L($m) { $m | Tee-Object -FilePath $log -Append }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    L 'Not admin — re-launching elevated...'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
. (Join-Path $PSScriptRoot '_winrt_await.ps1')

L "=== Repair run $(Get-Date -Format o) ==="

# Registry + services
Set-HotspotDhcpRegistry
Ensure-HotspotDhcpFirewall
foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc', 'Dhcp', 'RemoteAccess')) {
    try { Start-Service $svc -ErrorAction SilentlyContinue } catch {}
}

Disconnect-WifiClientForEthernetHotspot | Out-Null
Set-MobileHotspotBandRegistry2Ghz | Out-Null

# Start hotspot — API then poll
$mgr = Get-TetheringManager
if ($mgr) {
    L "Tethering before: $($mgr.TetheringOperationalState)"
    if ($mgr.TetheringOperationalState.ToString() -ne 'On') {
        $null = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'StartTethering' 60
        Start-Sleep -Seconds 10
        $mgr = Get-TetheringManager
        L "Tethering after API: $($mgr.TetheringOperationalState)"
    }
}

if (-not (Test-MobileHotspotGateway)) {
    L 'Opening mobile hotspot settings — if you see this, turn hotspot ON now.'
    Start-Process 'ms-settings:network-mobilehotspot'
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-MobileHotspotGateway) { break }
        Start-Sleep -Seconds 2
    }
}

L "Gateway 192.168.137.1: $(Test-MobileHotspotGateway)"
if (-not (Test-MobileHotspotGateway)) {
    L 'FAILED: Hotspot not running. Turn ON in Settings manually.'
    exit 2
}

Start-Sleep -Seconds 3
$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
L "Ethernet: $($eth.Name) | Hotspot NIC: $($ap.Name)"

if (-not $eth -or -not $ap) {
    L 'FAILED: adapter pair missing after hotspot on'
    exit 3
}

if (Enable-EthernetHotspotIcs -Quiet) {
    L 'ICS enable: OK'
} else {
    L 'ICS enable: trying alternate order...'
    $share = New-Object -ComObject HNetCfg.HNetShare
    $connMap = @{}
    foreach ($conn in @($share.EnumEveryConnection())) {
        try {
            $p = $share.NetConnectionProps($conn)
            $g = ($p.Guid.ToString().Trim('{}').ToLowerInvariant())
            $connMap[$g] = @{ cfg = $share.INetSharingConfigurationForINetConnection($conn); name = $p.Name }
        } catch {}
    }
    foreach ($k in $connMap.Keys) {
        try { if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing() } } catch {}
    }
    Start-Sleep -Seconds 1
    $ethG = ($eth.InterfaceGuid.ToString().Trim('{}').ToLowerInvariant())
    $apG = ($ap.InterfaceGuid.ToString().Trim('{}').ToLowerInvariant())
    $ethK = $null; $apK = $null
    foreach ($k in $connMap.Keys) {
        if ($k -eq $ethG) { $ethK = $k }
        if ($k -eq $apG) { $apK = $k }
    }
    if (-not $ethK) {
        $w = $eth.Name.ToLowerInvariant()
        foreach ($k in $connMap.Keys) { if (($connMap[$k].name -as [string]).ToLowerInvariant() -eq $w) { $ethK = $k } }
    }
    if (-not $apK) {
        $w = $ap.Name.ToLowerInvariant()
        foreach ($k in $connMap.Keys) { if (($connMap[$k].name -as [string]).ToLowerInvariant() -eq $w) { $apK = $k } }
    }
    if ($ethK -and $apK) {
        try {
            $connMap[$apK].cfg.EnableSharing(1)
            $connMap[$ethK].cfg.EnableSharing(0)
            L 'ICS alternate order applied'
        } catch {
            L "ICS error: $($_.Exception.Message)"
        }
    }
    Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 8
}

$s = Show-Ps5HotspotStatus
if ($s.Ready) {
    L 'SUCCESS — connect PS5 to osps'
    exit 0
}
L 'PARTIAL — check log; may need manual sharing on Ethernet'
exit 1
