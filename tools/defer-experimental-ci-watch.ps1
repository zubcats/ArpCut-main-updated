#Requires -Version 5.1
<#
  Wait (default 6 minutes) then run tools/watch-experimental-ci-and-install.ps1.

  Start from repo root with working directory set, e.g.:
    Start-Process powershell.exe -WorkingDirectory $pwd -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',(Resolve-Path '.\tools\defer-experimental-ci-watch.ps1')

  Log: %TEMP%\zubcut-ci-watch.log
#>
param(
    [int]$DelaySeconds = 360
)

$ErrorActionPreference = 'Stop'

try {
    $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $u = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($m) { $env:Path = $m + ';' + $env:Path }
    if ($u) { $env:Path = $u + ';' + $env:Path }
} catch {}

$repoRoot = Split-Path -Parent $PSScriptRoot
$watch = Join-Path $repoRoot 'tools\watch-experimental-ci-and-install.ps1'

if (-not (Test-Path -LiteralPath $watch)) {
    throw "Missing committed script: $watch"
}

Write-Host "Deferring $DelaySeconds s, then: $watch"
Start-Sleep -Seconds $DelaySeconds
Set-Location $repoRoot
& $watch
