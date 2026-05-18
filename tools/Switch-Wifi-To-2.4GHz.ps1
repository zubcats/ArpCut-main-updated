# Switch PC Wi-Fi uplink from 5 GHz to 2.4 GHz (same SSID, e.g. Wifi1).
# Run as Administrator — use the desktop "Switch WiFi to 2.4 GHz.cmd" shortcut.
$ErrorActionPreference = 'Continue'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator (use the desktop shortcut).'
    exit 1
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

Write-Host '=== Switch PC Wi-Fi to 2.4 GHz ==='
$iface = Get-WifiClientInterfaceName
$ssid = 'Wifi1'
if ((netsh wlan show interfaces 2>$null | Out-String) -match 'SSID\s*:\s*(.+)\r?\n') {
    $ssid = $Matches[1].Trim()
}

$ch = Get-WifiUplinkChannel
if ($ch -ge 1 -and $ch -le 14) {
    Write-Host "Already on 2.4 GHz (channel $ch, SSID $ssid)."
    exit 0
}

Write-Host "Current band: 5 GHz (channel $ch). Switching $ssid to 2.4 GHz..."
Stop-MobileHotspotIfOn | Out-Null
Start-Sleep -Seconds 3

netsh wlan disconnect interface="$iface" 2>$null | Out-Null
Start-Sleep -Seconds 3

$target = Find-BssidForSsidBand -Ssid $ssid -Band '2.4'
if (-not $target) {
    Write-Host "FAILED: No 2.4 GHz network found for '$ssid'."
    Write-Host 'In Settings -> Wi-Fi, connect to the 2.4 GHz version of your network manually.'
    exit 1
}

Write-Host "Connecting to 2.4 GHz BSSID $($target.Bssid)..."
netsh wlan connect name="$($target.Ssid)" ssid="$($target.Ssid)" interface="$iface" bss="$($target.Bssid)" 2>$null | Out-Null
Start-Sleep -Seconds 10

$ch2 = Get-WifiUplinkChannel
if ($ch2 -ge 1 -and $ch2 -le 14) {
    Write-Host "SUCCESS: PC is on 2.4 GHz (channel $ch2)."
    Write-Host 'For PS5 + hotspot: run "PS5 Hotspot ON (2.4 GHz).cmd" on your desktop.'
    exit 0
}

Write-Host "FAILED: Still on channel $ch2 (5 GHz)."
Write-Host 'Open Settings -> Wi-Fi -> pick the 2.4 GHz band for your network.'
exit 1
