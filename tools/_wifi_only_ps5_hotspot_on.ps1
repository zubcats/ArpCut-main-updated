# Wi-Fi-only: switch PC + hotspot to 2.4 GHz (same as _switch_24ghz_only_now.ps1). Run as Administrator.
$ErrorActionPreference = 'Stop'
$here = Join-Path $PSScriptRoot '_switch_24ghz_only_now.ps1'
if (-not (Test-Path $here)) { Write-Host 'Missing _switch_24ghz_only_now.ps1'; exit 1 }
& $here
exit $LASTEXITCODE
