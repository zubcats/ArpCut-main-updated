# Fix WinDivert service stuck on a deleted .sys path (WinDivertOpen error 3).
$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator'
    exit 1
}
$svc = 'WinDivert'
Write-Host '=== Repair WinDivert driver service ==='
sc.exe query $svc 2>$null
$reg = 'HKLM:\SYSTEM\CurrentControlSet\Services\WinDivert'
if (Test-Path $reg) {
    $img = (Get-ItemProperty $reg -ErrorAction SilentlyContinue).ImagePath
    Write-Host "Current ImagePath: $img"
}
sc.exe stop $svc 2>$null | Out-Null
Start-Sleep -Seconds 2
sc.exe delete $svc 2>$null | Out-Null
Start-Sleep -Seconds 1
Write-Host 'After delete:'
sc.exe query $svc 2>&1
Write-Host ''
Write-Host 'Now run ZubCut Kill again (Admin). WinDivert will register from ZubCut\windivert\WinDivert64.sys.'
