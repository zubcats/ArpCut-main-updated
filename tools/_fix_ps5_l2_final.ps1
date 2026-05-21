# Last-resort L2: disable random MAC, refresh hotspot AP, force DHCP offer path.
$log = Join-Path $PSScriptRoot '_fix_ps5_l2_final.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Get-Content $log
    exit
}
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
'' | Set-Content $log -Force
L "=== L2 final $(Get-Date -Format o) ==="

Set-NetAdapterRandomization -Name 'Wi-Fi' -Enabled $false -EA SilentlyContinue
L 'Wi-Fi random MAC: off'
netsh interface ipv4 set interface "Local Area Connection* 12" weakhostreceive=enabled weakhostsend=enabled forwarding=enabled 2>$null | Out-Null

$wifi = Get-NetAdapter | Where-Object { $_.Name -eq 'Wi-Fi' }
if ($wifi) {
    Disable-NetAdapterPowerManagement -Name $wifi.Name -EA SilentlyContinue
    Set-NetAdapterAdvancedProperty -Name $wifi.Name -DisplayName 'Roaming Aggressiveness' -DisplayValue 'Lowest' -EA SilentlyContinue
}

Stop-MobileHotspotIfOn | Out-Null
Start-Sleep 10
Restart-Service SharedAccess -Force -EA SilentlyContinue
Start-Sleep 4

Set-MobileHotspotBandRegistry2Ghz | Out-Null
$mgr = Get-TetheringManager
if ($mgr) {
    $cfg = $mgr.GetCurrentAccessPointConfiguration()
    $cfg.Band = Get-MobileHotspot2GhzBandValue
  # Keep SSID — changing breaks user muscle memory; refresh passphrase channel via restart only
    $null = Wait-WinRtAsync ($mgr.ConfigureAccessPointAsync($cfg)) 'Cfg' 45
    $null = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'Start' 60
}
Start-Sleep 10

$ap = Get-HotspotPrivateAdapter
Set-NetConnectionProfile -InterfaceIndex $ap.ifIndex -NetworkCategory Private -EA SilentlyContinue
Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
Ensure-HotspotDhcpFirewall

L "SSID=$($mgr.Configuration.SsidPrefix) band=$(Get-MobileHotspotApBandLabel (Get-TetheringManager))"
L "ICS=$(Test-EthernetHotspotIcsActive -EthernetAdapter (Get-EthernetUplinkAdapter) -HotspotAdapter $ap)"
try {
    $n = 0
    foreach ($c in (Get-TetheringManager).GetTetheringClients()) {
        $n++
        L "WIN SEES CLIENT: $($c.MacAddress) $($c.HostName)"
    }
    if ($n -eq 0) { L 'Windows sees ZERO tether clients — PS5 is not on this hotspot data path' }
} catch { L $_ }

Get-NetNeighbor -InterfaceAlias $ap.Name -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -like '192.168.137.*' -and $_.IPAddress -notlike '*.255' } |
    ForEach-Object { L "Neighbor $($_.IPAddress) $($_.LinkLayerAddress) $($_.State)" }
