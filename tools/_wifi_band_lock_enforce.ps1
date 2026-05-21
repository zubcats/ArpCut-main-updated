# Watchdog: re-apply 2.4 GHz lock if Windows roams to 5 GHz. Called by scheduled task.
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot '_wifi_band_lock.ps1')
if (-not (Test-WifiBandLockActive)) { exit 0 }
[void](Invoke-WifiBandLockEnforce -Quiet)
exit 0
