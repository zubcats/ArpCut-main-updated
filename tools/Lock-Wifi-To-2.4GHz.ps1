# Lock PC Wi-Fi to 2.4 GHz until Unlock-Wifi-To-5GHz.ps1 (blocks 5 GHz + watchdog task).
# Run as Administrator — use Lock-Wifi-To-2.4GHz.cmd
$ErrorActionPreference = 'Continue'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator (use the .cmd shortcut).'
    exit 1
}

. (Join-Path $PSScriptRoot '_wifi_band_lock.ps1')

Write-Host '=== Lock Wi-Fi to 2.4 GHz (persistent) ==='
if (Test-WifiBandLockActive) {
    Write-Host 'Lock already active — refreshing enforcement...'
    if (Invoke-WifiBandLockEnforce) { exit 0 }
    exit 1
}

if (Enable-WifiBandLock24Ghz) { exit 0 }
exit 1
