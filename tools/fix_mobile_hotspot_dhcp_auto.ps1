# Non-interactive hotspot DHCP fix (for elevated/automated runs).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_hotspot_fix_result.txt'
function Log([string]$m) { $m | Tee-Object -FilePath $log -Append }
'' | Set-Content -Path $log -Encoding UTF8
function Test-HotspotDhcp {
    $listen67 = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
    $gw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1
    return @{ Dhcp = [bool]$listen67; Gw = [bool]$gw }
}

$before = Test-HotspotDhcp
Log "BEFORE dhcp67=$($before.Dhcp) gw137=$($before.Gw)"

foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc')) {
    try {
        $s = Get-Service -Name $svc -ErrorAction Stop
        if ($s.Status -eq 'Running') {
            Restart-Service -Name $svc -Force -ErrorAction Stop
        } else {
            Start-Service -Name $svc -ErrorAction Stop
        }
        Log "OK service $svc"
    } catch {
        Log "WARN service $svc : $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 2
$after = Test-HotspotDhcp
Log "AFTER dhcp67=$($after.Dhcp) gw137=$($after.Gw)"
if (-not $after.Dhcp) { exit 1 }
exit 0
