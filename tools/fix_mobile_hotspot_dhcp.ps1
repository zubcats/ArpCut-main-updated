# Restore Mobile Hotspot DHCP when clients (e.g. PS5) cannot obtain an IP.
# Right-click -> Run as administrator.
$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator.'
    exit 1
}

function Test-HotspotDhcp {
    $listen67 = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
    $gw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1
    return @{
        DhcpListening = [bool]$listen67
        Gateway       = [bool]$gw
    }
}

Write-Host 'Before:'
$before = Test-HotspotDhcp
Write-Host ('  192.168.137.1 on hotspot adapter: ' + $before.Gateway)
Write-Host ('  DHCP listening (UDP 67): ' + $before.DhcpListening)

foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc')) {
    try {
        if ((Get-Service -Name $svc -ErrorAction Stop).Status -ne 'Running') {
            Start-Service -Name $svc -ErrorAction Stop
        } else {
            Restart-Service -Name $svc -Force -ErrorAction SilentlyContinue
        }
        Write-Host ('  Restarted ' + $svc)
    } catch {
        Write-Host ('  WARN: ' + $svc + ' - ' + $_.Exception.Message)
    }
}

Write-Host ''
Write-Host 'Now do this in Windows Settings:'
Write-Host '  Network -> Mobile hotspot -> OFF'
Write-Host '  Wait 15 seconds'
Write-Host '  Mobile hotspot -> ON'
Write-Host '  Reconnect PS5 to the PC hotspot Wi-Fi (not your router)'
Write-Host ''
Read-Host 'Press Enter after hotspot is ON again'

$after = Test-HotspotDhcp
Write-Host 'After:'
Write-Host ('  192.168.137.1 on hotspot adapter: ' + $after.Gateway)
Write-Host ('  DHCP listening (UDP 67): ' + $after.DhcpListening)

if (-not $after.DhcpListening) {
    Write-Host ''
    Write-Host 'DHCP still not running. Try:'
    Write-Host '  1. Reboot the PC'
    Write-Host '  2. Settings -> Network -> Advanced network settings -> Network reset (last resort)'
    Write-Host '  3. Do NOT run ZubCut Repair hotspot while testing — it clears ICS sharing'
    exit 1
}

Write-Host ''
Write-Host 'DHCP looks up. PS5 should get 192.168.137.x within a few seconds.'
exit 0
