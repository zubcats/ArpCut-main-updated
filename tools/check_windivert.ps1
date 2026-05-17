# Check WinDivert bundle for Clumsy / ICS hotspot lag (run from repo root).
$ErrorActionPreference = 'Continue'
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$repo = Split-Path -Parent $root
Set-Location $repo

$sysDrv = Join-Path $env:SystemRoot 'System32\drivers\WinDivert64.sys'
$bundles = @(
    (Join-Path $repo 'windivert'),
    (Join-Path $repo 'installer\windivert')
)

Write-Host '=== WinDivert check (ICS / Clumsy hotspot) ==='
Write-Host "System driver (optional): $(Test-Path -LiteralPath $sysDrv)  $sysDrv"
foreach ($dir in $bundles) {
    $dll = Join-Path $dir 'WinDivert.dll'
    $sys = Join-Path $dir 'WinDivert64.sys'
    Write-Host ""
    Write-Host "Bundle: $dir"
    Write-Host "  WinDivert.dll:    $(if (Test-Path $dll) { 'OK' } else { 'MISSING' })"
    Write-Host "  WinDivert64.sys:  $(if (Test-Path $sys) { 'OK' } else { 'MISSING' })"
}

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if ($py) {
    Write-Host ''
    Write-Host '=== ZubCut Python probe ==='
    & $py.Name -c @"
import sys, os
sys.path.insert(0, os.path.join(r'$repo', 'src'))
from tools.clumsy_inline import windivert_driver_installed, clumsy_runtime_ready, clumsy_ics_lag_can_use_windivert
from tools.ics_windivert_shaper import _windivert_dll_path
from tools.utils_gui import get_settings
print('clumsy_mode:', get_settings('clumsy_mode'))
print('dll_path:', _windivert_dll_path())
print('driver_installed:', windivert_driver_installed())
print('runtime_ready:', clumsy_runtime_ready())
print('ics_lag_ready (example 137.x):', clumsy_ics_lag_can_use_windivert({'ip':'192.168.137.50'}))
"@
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host ''
Write-Host "Running as Administrator: $isAdmin (ZubCut needs Admin for WinDivert on hotspot)"
if (-not (Test-Path (Join-Path $repo 'windivert\WinDivert.dll'))) {
    Write-Host ''
    Write-Host 'Fix: pwsh -File installer\fetch_windivert.ps1'
    exit 1
}
exit 0
