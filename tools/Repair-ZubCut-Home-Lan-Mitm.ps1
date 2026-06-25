# Reset Windows IP forwarding + stale ZubCut blocks (home LAN Kill/Lag/Dupe).
$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Re-launching as Administrator...'
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

Write-Host '=== Disable Windows IP forwarding (MITM cut requires this OFF) ==='
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' `
    -Name 'IPEnableRouter' -Value 0 -Type DWord -Force -ErrorAction SilentlyContinue
netsh interface ipv4 set global forwarding=disabled | Out-Null
Write-Host '  IPEnableRouter=0, global forwarding=disabled'

Write-Host ''
Write-Host '=== Clear stale ZubCut firewall / WinDivert blocks ==='
$repo = Split-Path -Parent $PSScriptRoot
$clear = Join-Path $repo 'tools\clear_stale_zubcut_attacks.py'
if (Test-Path $clear) {
    & py $clear
    if ($LASTEXITCODE -ne 0) { & python $clear }
} else {
    Write-Host "  (skip: $clear not found)"
}

Write-Host ''
Write-Host 'Done. Close ZubCut, then open it with Run as administrator.'
Write-Host 'Rescan, select PS5 DUPE (.165), try Kill.'
Write-Host 'Press Enter to close.'
Read-Host | Out-Null
