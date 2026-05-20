# Laptop: Ethernet = internet, built-in Wi-Fi = Mobile Hotspot for PS5 (not USB dongle path).
# Run as Administrator on the LAPTOP while Ethernet cable is plugged in.
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_laptop_hotspot_setup.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    L 'Click Yes on UAC'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Get-Content $log
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
. (Join-Path $PSScriptRoot '_winrt_await.ps1')
'' | Set-Content $log -Force
L "=== Laptop Ethernet + Wi-Fi hotspot $(Get-Date -Format o) ==="

# 1) Ethernet must be internet
$eth = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'Ethernet|Gigabit|GbE' -and
    $_.InterfaceDescription -notmatch 'Virtual|Bluetooth|Wi-Fi|Wireless|USB'
} | Select-Object -First 1
if (-not $eth) {
    L 'ERROR: Plug Ethernet into laptop first (Ethernet must show Connected in ncpa.cpl).'
    exit 1
}
L "Internet: $($eth.Name) ($($eth.InterfaceDescription))"

# 2) Built-in Wi-Fi only — disconnect from home router (same radio cannot be client + AP)
$wifi = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi|802\.11' -and
    $_.InterfaceDescription -notmatch 'USB|Direct|Virtual|Hosted|8821'
} | Select-Object -First 1
if (-not $wifi) {
    $wifi = Get-NetAdapter -Name 'Wi-Fi' -EA SilentlyContinue
}
if ($wifi) {
    if ($wifi.Status -eq 'Disabled') {
        Enable-NetAdapter -Name $wifi.Name -Confirm:$false -EA SilentlyContinue
        Start-Sleep 4
    }
    $wlan = netsh wlan show interfaces 2>$null | Out-String
    if ($wlan -match 'State\s*:\s*connected') {
        L "Disconnecting $($wifi.Name) from router Wi-Fi (required for hotspot)..."
        netsh wlan disconnect interface="$($wifi.Name)" 2>$null | Out-Null
        Start-Sleep 3
    }
    Set-NetIPInterface -InterfaceIndex $wifi.ifIndex -AddressFamily IPv4 -InterfaceMetric 8000 -EA SilentlyContinue
    L "Wi-Fi radio: $($wifi.Name) — not router client, ready for hotspot"
} else {
    L 'WARN: No built-in Wi-Fi adapter found'
}

Set-NetIPInterface -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -InterfaceMetric 10 -EA SilentlyContinue
Set-NetConnectionProfile -InterfaceIndex $eth.ifIndex -NetworkCategory Private -EA SilentlyContinue

# 3) Unplug USB Wi-Fi dongle if present (optional warning)
$usbWifi = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match '8821|USB.*Wireless|802\.11ac USB'
}
if ($usbWifi) {
    L "WARN: USB Wi-Fi still present: $($usbWifi.Name) — unplug dongle on laptop for clean hotspot"
}

# 4) Hotspot 2.4 GHz
Set-MobileHotspotBandRegistry2Ghz | Out-Null
$icsReg = 'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings'
Set-ItemProperty -Path $icsReg -Name WiFiHotspotEncryption -Value 1 -Type DWord -Force -EA SilentlyContinue

Stop-MobileHotspotIfOn | Out-Null
Start-Sleep 8
Restart-Service WlanSvc -Force -EA SilentlyContinue
Start-Sleep 4

$mgr = Get-TetheringManager
if (-not $mgr) {
    L 'ERROR: No tethering manager — enable Mobile Hotspot once in Settings'
    exit 1
}
$cfg = $mgr.GetCurrentAccessPointConfiguration()
$cfg.Ssid = 'ZubCutPS5'
$cfg.Passphrase = 'Connect12345'
$cfg.Band = Get-MobileHotspot2GhzBandValue
$null = Wait-WinRtAsync ($mgr.ConfigureAccessPointAsync($cfg)) 'Cfg' 90
$null = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'Start' 90
Start-Sleep 12

$ap = Get-HotspotPrivateAdapter
Enable-EthernetHotspotIcs -Quiet | Out-Null
Ensure-HotspotDhcpFirewall

$mgr2 = Get-TetheringManager
L "Hotspot: $($mgr2.TetheringOperationalState) SSID=$($cfg.Ssid) band=$(Get-MobileHotspotApBandLabel $mgr2)"
L "Gateway: $(Test-MobileHotspotGateway) DHCP: $(Test-HotspotDhcpListening)"
L "ICS: $(Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)"
L "Hotspot NIC: $($ap.Name)"

L ''
L 'PS5: forget old networks, connect ZubCutPS5 / Connect12345, IP Automatic'
L 'Settings -> Mobile hotspot must show ON and same password'
