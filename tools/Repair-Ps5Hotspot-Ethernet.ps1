# One-shot fix: Ethernet internet + 2.4 GHz hotspot ON + sharing + DHCP for PS5.
$ErrorActionPreference = 'Continue'
$logPath = Join-Path $PSScriptRoot '_repair_ps5_hotspot_last.log'
Start-Transcript -Path $logPath -Force | Out-Null

try {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host 'ERROR: Run as Administrator (right-click -> Run as administrator).'
        exit 1
    }

    . (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

    if (Repair-Ps5HotspotEthernet) { exit 0 }
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
