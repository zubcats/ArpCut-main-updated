# Full Wi-Fi recovery: band lock off + mobile hotspot off + PC back on 5 GHz.
# Same fix as PS5 Hotspot OFF. Run as Administrator — use Unlock-Wifi-To-5GHz.cmd
$ErrorActionPreference = 'Continue'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator (use the desktop shortcut).'
    exit 1
}

. (Join-Path $PSScriptRoot '_wifi_band_lock.ps1')

if (Restore-PcWifiNormal) { exit 0 }
exit 0
