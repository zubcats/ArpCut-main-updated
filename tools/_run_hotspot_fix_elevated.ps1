# Self-elevate then run full ZubCut hotspot prep + log
$log = Join-Path $PSScriptRoot '_hotspot_fix_log.txt'
$repo = Split-Path $PSScriptRoot -Parent

function Write-Log([string]$m) {
    Write-Host $m
    Add-Content -Path $log -Value $m -ErrorAction SilentlyContinue
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $admin) {
    '' | Set-Content -Path $log -Force
    Write-Log 'Requesting Administrator (click Yes on UAC)...'
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList $arg
    if (Test-Path $log) { Get-Content $log }
    exit $LASTEXITCODE
}

'' | Set-Content -Path $log -Force
Write-Log "=== ZubCut hotspot fix $(Get-Date -Format o) ==="

# 1) Built-in ICS script
$icsScript = Join-Path $PSScriptRoot '_run_hotspot_fix_now.ps1'
if (Test-Path $icsScript) {
    Write-Log '--- ICS + firewall ---'
    & $icsScript 2>&1 | ForEach-Object { Write-Log $_ }
}

# 2) Python prepare_pc_mobile_hotspot (tethering toggle + registry)
$py = @('python', 'py', 'python3') | ForEach-Object {
    $c = Get-Command $_ -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { $c.Source; break }
}
if ($py) {
    Write-Log "--- Python prep via $py ---"
    $code = @"
import sys
sys.path.insert(0, r'$repo')
from src.tools.clumsy_ics import prepare_pc_mobile_hotspot, repair_clumsy_network_sharing
ok1, msg1 = prepare_pc_mobile_hotspot()
print('prepare:', ok1, msg1)
ok2, msg2 = repair_clumsy_network_sharing()
print('repair:', ok2, msg2)
sys.exit(0 if ok1 else 1)
"@
    $out = & $py -c $code 2>&1
    $out | ForEach-Object { Write-Log $_ }
} else {
    Write-Log 'WARN: Python not found; skipped prepare_pc_mobile_hotspot'
}

Write-Log '--- Final state ---'
Write-Log ('  192.168.137.1: ' + [bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' }))
Write-Log ('  DHCP UDP 67: ' + [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue))

Get-Content $log
