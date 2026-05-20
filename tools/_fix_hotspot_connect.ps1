$log = Join-Path $PSScriptRoot '_fix_hotspot_connect.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Get-Content $log
    exit
}
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
. (Join-Path $PSScriptRoot '_winrt_await.ps1')
'' | Set-Content $log -Force
L "=== Fix hotspot connect $(Get-Date -Format o) ==="

# Internet profile must exist (Ethernet)
$prof = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if (-not $prof) { L 'ERROR: No internet profile - is Ethernet connected?'; exit 1 }
L "Internet profile: $($prof.ProfileName)"

Disconnect-WifiClientForEthernetHotspot | Out-Null
$mgr = Get-TetheringManager
if (-not $mgr) { L 'ERROR: No TetheringManager'; exit 1 }

try {
    $cap = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::GetTetheringCapability()
    L "TetheringCapability: $cap"
} catch { L "Capability: $_" }

Stop-MobileHotspotIfOn | Out-Null
Start-Sleep -Seconds 10
Restart-Service WlanSvc -Force -EA SilentlyContinue
Start-Sleep -Seconds 5
Restart-Service icssvc -Force -EA SilentlyContinue
Start-Sleep -Seconds 3

$mgr = Get-TetheringManager
$cfg = $mgr.GetCurrentAccessPointConfiguration()
L "OLD SSID=$($cfg.Ssid) passLen=$($cfg.Passphrase.Length)"

# Fresh SSID + simple password (WPA2-PSK via WinRT default)
$newSsid = 'ZubCutPS5'
$newPass = 'Connect12345'
$cfg.Ssid = $newSsid
$cfg.Passphrase = $newPass
$cfg.Band = Get-MobileHotspot2GhzBandValue
Set-MobileHotspotBandRegistry2Ghz | Out-Null

L "NEW SSID=$newSsid PASSWORD=$newPass"
$op = $mgr.ConfigureAccessPointAsync($cfg)
$r = Wait-WinRtAsync $op 'ConfigureAP' 60
L "ConfigureAP result: $r"

$op2 = $mgr.StartTetheringAsync()
$r2 = Wait-WinRtAsync $op2 'Start' 60
L "StartTethering result: $r2"
Start-Sleep -Seconds 15

$mgr3 = Get-TetheringManager
L "State=$($mgr3.TetheringOperationalState) band=$(Get-MobileHotspotApBandLabel $mgr3)"
L "Gateway=$(Test-MobileHotspotGateway) DHCP=$(Test-HotspotDhcpListening)"

$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
Enable-EthernetHotspotIcs -Quiet | Out-Null
L "ICS=$(Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)"

try {
    foreach ($c in $mgr3.GetTetheringClients()) { L "CLIENT $($c.MacAddress)" }
} catch { L "Clients: $_" }

L ''
L '*** CONNECT TO THIS NETWORK (not osps): ***'
L "SSID: $newSsid"
L "PASSWORD: $newPass"
L 'Forget osps on phone/PS5. Use ZubCutPS5 instead.'
