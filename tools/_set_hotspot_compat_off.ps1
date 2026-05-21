# Turn OFF "Maximize compatibility" = hotspot 5 GHz (not 2.4).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_hotspot_compat_off.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    L 'UAC — click Yes'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

'' | Set-Content $log -Force
L "=== Maximize compatibility OFF (5 GHz) $(Get-Date -Format o) ==="

Disconnect-WifiClientForEthernetHotspot | Out-Null

# Registry: 2 = 5 GHz, 1 = 2.4 GHz (Maximize compatibility)
foreach ($rp in @(
    'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings',
    'HKCU:\Software\Microsoft\WCM\Tethering\Settings'
)) {
    if (-not (Test-Path $rp)) {
        try { New-Item -Path $rp -Force | Out-Null } catch {}
    }
    foreach ($name in @('TetheringBand', 'WiFiBand', 'PreferredBand')) {
        try {
            Set-ItemProperty -Path $rp -Name $name -Value 2 -Type DWord -Force -EA SilentlyContinue
        } catch {}
    }
}
L 'Registry band set to 5 GHz (2)'

if (-not (Ensure-TetheringWinRTLoaded)) {
    L 'ERROR: WinRT tethering not available'
    exit 1
}

$mgr = Get-TetheringManager
if (-not $mgr) {
    L 'ERROR: No tethering manager — enable Mobile hotspot in Settings first'
    exit 1
}

if ($mgr.TetheringOperationalState.ToString() -eq 'On') {
    L 'Stopping hotspot...'
    Stop-MobileHotspotIfOn | Out-Null
    Start-Sleep -Seconds 5
    $mgr = Get-TetheringManager
}

$band5 = 2
try {
    $band5 = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringWiFiBand]::FiveGigahertz
} catch {}

$cfg = $mgr.GetCurrentAccessPointConfiguration()
if ($null -eq $cfg) {
    L 'ERROR: Could not read hotspot AP config'
    exit 1
}

L "Band was: $($cfg.Band)"
$cfg.Band = $band5
$op = $mgr.ConfigureAccessPointAsync($cfg)
if (-not (Wait-WinRtAsync $op 'ConfigureAccessPoint' 45)) {
    L 'WARN: ConfigureAccessPoint timed out — trying start anyway'
}

L 'Starting hotspot on 5 GHz...'
$op2 = $mgr.StartTetheringAsync()
if (-not (Wait-WinRtAsync $op2 'StartTethering' 60)) {
    L 'ERROR: StartTethering failed'
    exit 1
}
Start-Sleep -Seconds 10

$mgr2 = Get-TetheringManager
$bandLabel = Get-MobileHotspotApBandLabel $mgr2
L "Hotspot state: $($mgr2.TetheringOperationalState)"
L "Band now: $bandLabel"

$gw = Test-MobileHotspotGateway
$dhcp = Test-HotspotDhcpListening
L "Gateway 192.168.137.1: $gw  DHCP67: $dhcp"

if ($gw -and $dhcp) {
    Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
    Ensure-HotspotDhcpFirewall
    L 'ICS left as-is; DHCP firewall refreshed'
}

L ''
L 'PS5: Forget osps -> reconnect -> wait 2 min -> test'
L 'If worse: run tools\_set_hotspot_compat_on.ps1 to go back to 2.4 GHz'
