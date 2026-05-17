# Switch PC + hotspot to 2.4 GHz only (Wi-Fi-only). Run as Administrator.
$ErrorActionPreference = 'Continue'
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$log = Join-Path $root '_switch_24ghz_result.txt'
if (Test-Path $log) { Remove-Item $log -Force }
function L($m) { Add-Content $log $m -Encoding UTF8; Write-Host $m }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    L 'ERROR: Run as Administrator'; exit 1
}

. (Join-Path $root '_hotspot_2ghz_apply.ps1')

L '=== Switch to 2.4 GHz only ==='
Stop-MobileHotspotIfOn | Out-Null
Start-Sleep -Seconds 5
Set-MobileHotspotBandRegistry2Ghz | Out-Null
Restart-IcssvcIfNeeded | Out-Null

$iface = Get-WifiClientInterfaceName
$ssid = 'Wifi1'
if ((netsh wlan show interfaces 2>$null | Out-String) -match 'SSID\s*:\s*(.+)\r?\n') {
    $ssid = $Matches[1].Trim()
}
netsh wlan disconnect interface="$iface" 2>$null | Out-Null
Start-Sleep -Seconds 4
$target = Find-BssidForSsidBand -Ssid $ssid -Band '2.4'
if (-not $target) {
    L "FAILED: No 2.4 GHz BSSID found for $ssid — open Wi-Fi and connect to the 2.4 GHz band of Wifi1 manually."
    exit 1
}
L "Target 2.4 BSSID: $($target.Bssid)"

$out = netsh wlan connect name="$ssid" ssid="$ssid" interface="$iface" bss="$($target.Bssid)" 2>&1 | Out-String
L "connect: $out"
Start-Sleep -Seconds 12
$ch = Get-WifiUplinkChannel
L "PC channel after connect: $ch"
if ($ch -gt 14) {
    L 'FAILED: PC still on 5 GHz — in Windows Settings: Wi-Fi -> Wifi1 -> connect using the 2.4 GHz network (not 5 GHz).'
    exit 1
}

$mgr = Get-TetheringManager
if (-not $mgr) { L 'FAILED: no tethering manager'; exit 1 }
if (-not (Configure-MobileHotspotAccessPoint2Ghz $mgr $false)) { L 'WARN: ConfigureAccessPoint' }
if (-not (Start-MobileHotspotAfter2GhzConfig)) { L 'WARN: StartTethering — turn hotspot ON in Settings' }

$mgr2 = Get-TetheringManager
$ap = ''
if ($mgr2) { try { $ap = [string]$mgr2.GetCurrentAccessPointConfiguration().Band } catch {} }
L "Hotspot: $($mgr2.TetheringOperationalState) AP.Band=$ap"
L 'DONE: PC + hotspot should be 2.4 GHz. Connect PS5 to osps.'
exit 0
