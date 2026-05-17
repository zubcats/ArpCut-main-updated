# Non-interactive 2.4 GHz hotspot fix (ZubCut).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_hotspot_2ghz_result.txt'
function L([string]$m) { Add-Content -Path $log -Value $m -Encoding UTF8; Write-Host $m }

if (Test-Path $log) { Remove-Item $log -Force }
L '=== ZubCut: force Mobile Hotspot to 2.4 GHz ==='

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
L "Administrator: $isAdmin"
if (-not $isAdmin) {
    L 'FAILED: not running as Administrator'
    exit 1
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

try {
    $mgr = Get-TetheringManager
    if (-not $mgr) { throw 'No internet connection profile (connect PC Wi-Fi to the router first).' }
    L "Before: State=$($mgr.TetheringOperationalState) Band=$(Get-MobileHotspotBandLabel $mgr) SSID=$($mgr.Configuration.SsidPrefix)"

    if (-not (Ensure-MobileHotspot2GhzBand)) {
        throw 'Ensure-MobileHotspot2GhzBand failed'
    }
    Start-MobileHotspotAfter2GhzConfig | Out-Null
    if (-not (Test-EthernetInternetUplink)) {
        Connect-WifiUplinkTo5Ghz | Out-Null
    }

    $mgr2 = Get-TetheringManager
    $afterBand = Get-MobileHotspotBandLabel $mgr2
    L "After: State=$($mgr2.TetheringOperationalState) Band=$afterBand SSID=$($mgr2.Configuration.SsidPrefix)"

    if ($afterBand -match 'TwoPointFour') {
        L 'SUCCESS: Hotspot band is 2.4 GHz.'
        exit 0
    }
    if ($afterBand -match 'Five|5G') {
        L 'WARNING: Band still reports 5 GHz — adapter may not support 2.4 GHz hotspot.'
        exit 2
    }
    L "DONE: Band=$afterBand (verify in Settings -> Mobile hotspot)"
    exit 0
} catch {
    L "ERROR: $($_.Exception.Message)"
    exit 1
}
