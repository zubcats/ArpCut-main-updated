# Max compatibility OFF via Auto band (when 5 GHz fails on USB dongle).
$log = Join-Path $PSScriptRoot '_hotspot_compat_off.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
'' | Set-Content $log -Force
L "=== Compat OFF (Auto band) $(Get-Date -Format o) ==="
Disconnect-WifiClientForEthernetHotspot | Out-Null
foreach ($rp in @('HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings', 'HKCU:\Software\Microsoft\WCM\Tethering\Settings')) {
    if (-not (Test-Path $rp)) { try { New-Item -Path $rp -Force | Out-Null } catch {} }
    foreach ($n in @('TetheringBand', 'WiFiBand', 'PreferredBand')) {
        Set-ItemProperty -Path $rp -Name $n -Value 0 -Type DWord -Force -EA SilentlyContinue
    }
}
L 'Registry band=0 (Auto)'
if (-not (Ensure-TetheringWinRTLoaded)) { L 'ERROR WinRT'; exit 1 }
$mgr = Get-TetheringManager
if (-not $mgr) { L 'ERROR no manager'; exit 1 }
Stop-MobileHotspotIfOn | Out-Null
Start-Sleep 4
$mgr = Get-TetheringManager
$cfg = $mgr.GetCurrentAccessPointConfiguration()
$auto = 0
try { $auto = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringWiFiBand]::Automatic } catch {}
$cfg.Band = $auto
$null = Wait-WinRtAsync ($mgr.ConfigureAccessPointAsync($cfg)) 'Cfg' 45
$ok = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'Start' 60
Start-Sleep 8
$m2 = Get-TetheringManager
L "State: $($m2.TetheringOperationalState) Band: $(Get-MobileHotspotApBandLabel $m2)"
L "Gateway: $(Test-MobileHotspotGateway) DHCP: $(Test-HotspotDhcpListening)"
if (Test-MobileHotspotGateway) {
    Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
    Ensure-HotspotDhcpFirewall
}
