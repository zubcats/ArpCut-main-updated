#Requires -Version 5.1
<#
  Wait before starting the watcher (CI + release tag/asset propagation). Default
  6 minutes; override with -DelaySeconds. Then runs the local-only watcher that
  blocks on GitHub Actions and launches the experimental installer.

  Intended to be started in a separate process so the agent does not block:
    Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Minimized','-File', <this-file>

  Requires: gh auth login, .local/watch-exp-ci-and-update.ps1 (see repo docs / agent rule).
#>
param(
    [int]$DelaySeconds = 360
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$watch = Join-Path $repoRoot '.local\watch-exp-ci-and-update.ps1'

if (-not (Test-Path -LiteralPath $watch)) {
    Write-Error "Missing $watch — add .local/watch-exp-ci-and-update.ps1 (local-only)."
}

Write-Host "Deferring $DelaySeconds s, then running: $watch"
Start-Sleep -Seconds $DelaySeconds
Set-Location $repoRoot
& $watch
