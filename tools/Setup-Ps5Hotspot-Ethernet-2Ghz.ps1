# Normal setup: Ethernet internet -> 2.4 GHz mobile hotspot (no Wi-Fi band lock / no 5 GHz PC Wi-Fi).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_setup_ps5_hotspot_ethernet.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    L 'Administrator required — click Yes on UAC'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
$lockScript = Join-Path $PSScriptRoot '_wifi_band_lock.ps1'
if (Test-Path $lockScript) {
    . $lockScript
    if (Get-Command Unregister-WifiBandLockWatchdog -ErrorAction SilentlyContinue) {
        Unregister-WifiBandLockWatchdog
    }
    if (Get-Command Clear-WifiBandLockState -ErrorAction SilentlyContinue) {
        Clear-WifiBandLockState
    }
    L 'Removed Wi-Fi band lock (if any) — hotspot only, not locked PC Wi-Fi'
}

'' | Set-Content $log -Force
L "=== Ethernet + 2.4 GHz hotspot (no lock) $(Get-Date -Format o) ==="

if (-not (Test-EthernetInternetUplink)) {
    L 'ERROR: Plug Ethernet to router first (Ethernet 2 = Connected).'
    exit 1
}

# PC uses Ethernet for internet — Wi-Fi radio only for hotspot (stay disconnected from router)
Disconnect-WifiClientForEthernetHotspot | Out-Null
$eth = Get-EthernetUplinkAdapter
Set-NetIPInterface -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -InterfaceMetric 10 -EA SilentlyContinue
Set-NetConnectionProfile -InterfaceIndex $eth.ifIndex -NetworkCategory Private -EA SilentlyContinue
L "Internet: $($eth.Name)"

foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc')) {
    Start-Service $svc -EA SilentlyContinue
}

# 2.4 GHz hotspot once (not Force-MobileHotspot2Ghz / no watchdog lock)
Set-MobileHotspotBandRegistry2Ghz | Out-Null
$mgr = Get-TetheringManager
if (-not $mgr) {
    L 'ERROR: Open Settings -> Mobile hotspot once, then re-run.'
    exit 1
}
if ($mgr.TetheringOperationalState.ToString() -eq 'On') {
    Stop-MobileHotspotIfOn | Out-Null
    Start-Sleep -Seconds 4
    $mgr = Get-TetheringManager
}
if (-not (Configure-MobileHotspotAccessPoint2Ghz $mgr $false)) {
    L 'WARN: Could not set 2.4 GHz via API — set band to 2.4 GHz in Settings manually'
}
if (-not (Start-MobileHotspotAfter2GhzConfig)) {
    L 'ERROR: Turn Mobile hotspot ON in Settings'
    exit 1
}

$mgr2 = Get-TetheringManager
L "Hotspot: $($mgr2.TetheringOperationalState) band=$(Get-MobileHotspotApBandLabel $mgr2)"

Ensure-HotspotDhcpFirewall
# Never force COM ICS reset here — use Sharing tab manually if ICS=False below.
Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
if (-not (Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter (Get-HotspotPrivateAdapter))) {
    L 'ICS not active — set manually: Ethernet 2 Sharing -> allow -> home = Local Area Connection* 12'
}

$s = Test-Ps5HotspotReady
L "Gateway: $($s.Gateway) DHCP: $($s.Dhcp) ICS: $($s.IcsSharing) Ready: $($s.Ready)"
L ''
L 'Done. PC internet = Ethernet only. Hotspot = 2.4 GHz osps (not band-locked).'
L 'PS5: connect to osps; IP automatic or 192.168.137.2 / GW 192.168.137.1 / DNS 8.8.8.8'
