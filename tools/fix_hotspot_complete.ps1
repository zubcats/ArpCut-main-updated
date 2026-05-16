# Wrapper: requires hotspot ON in Settings first (no API - avoids frozen window).
& (Join-Path $PSScriptRoot 'enable_hotspot_ics_now.ps1')
exit $LASTEXITCODE
