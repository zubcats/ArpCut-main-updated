# Delegates to Stop-Ps5Hotspot.ps1 (Ethernet-aware).
$here = Join-Path $PSScriptRoot 'Stop-Ps5Hotspot.ps1'
& $here
exit $LASTEXITCODE
