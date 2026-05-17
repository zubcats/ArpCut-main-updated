# Quick ICS / WinDivert diagnostics for PS5 on PC Mobile Hotspot.
# Run in PowerShell as Administrator.

$ErrorActionPreference = 'Continue'
Write-Host '=== ZubCut ICS lag diagnostics ===' -ForegroundColor Cyan

$zub = @(
    "${env:ProgramFiles}\ZubCut\ZubCut.exe",
    "${env:ProgramFiles(x86)}\ZubCut\ZubCut.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($zub) { Write-Host "ZubCut: $zub" } else { Write-Host 'ZubCut.exe not found under Program Files' -ForegroundColor Yellow }

$wd = @(
    "${env:ProgramFiles}\ZubCut\windivert\WinDivert.dll",
    "${env:ProgramFiles}\ZubCut\windivert\WinDivert64.sys"
)
foreach ($p in $wd) {
    if (Test-Path $p) { Write-Host "OK  $p" -ForegroundColor Green }
    else { Write-Host "MISSING $p" -ForegroundColor Red }
}

$flag = "${env:ProgramFiles}\ZubCut\clumsy_mode_bundle.flag"
if (Test-Path $flag) { Write-Host "OK  clumsy_mode_bundle.flag" -ForegroundColor Green }
else { Write-Host 'MISSING clumsy_mode_bundle.flag (reinstall with Clumsy mode)' -ForegroundColor Red }

$state = Join-Path $env:APPDATA 'ZubCut\clumsy_ics_state.json'
if (Test-Path $state) {
    Write-Host "ICS state: $state"
    Get-Content $state -Raw | Write-Host
} else {
    Write-Host 'No clumsy_ics_state.json — enable Clumsy mode in ZubCut Settings' -ForegroundColor Yellow
}

Write-Host "`n--- Hotspot gateway (expect 192.168.137.1) ---"
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -like '192.168.137.*' } |
    Format-Table InterfaceAlias, IPAddress, PrefixLength -AutoSize

Write-Host '--- ARP on hotspot (PS5 should be 192.168.137.x) ---'
arp -a | Select-String '192\.168\.137\.'

Write-Host '--- SharedAccess (ICS) ---'
Get-Service SharedAccess | Format-Table Status, StartType -AutoSize

Write-Host "`nIf WinDivert files exist but lag still fails: run ZubCut as Administrator, Clumsy ON, PS5 on PC hotspot Wi-Fi only." -ForegroundColor Cyan
