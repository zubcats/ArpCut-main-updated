# SSID visible but cannot connect: force WPA2 + re-apply password.
$log = Join-Path $PSScriptRoot '_fix_hotspot_wpa2.log'
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
L "=== WPA2 + password fix $(Get-Date -Format o) ==="

$icsReg = 'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings'
if (-not (Test-Path $icsReg)) { New-Item -Path $icsReg -Force | Out-Null }
# 1 = WPA2-PSK (avoid WPA3 association failures on PS5 / some phones)
foreach ($n in @('WiFiHotspotEncryption', 'HotspotEncryption')) {
    try { Set-ItemProperty -Path $icsReg -Name $n -Value 1 -Type DWord -Force -EA SilentlyContinue; L "Set $n=1 (WPA2)" } catch {}
}
Set-MobileHotspotBandRegistry2Ghz | Out-Null

$ssid = 'ZubCutPS5'
$pass = 'Connect12345'

Stop-MobileHotspotIfOn | Out-Null
Start-Sleep -Seconds 8
Restart-Service icssvc -Force -EA SilentlyContinue
Start-Sleep -Seconds 5

$mgr = Get-TetheringManager
if (-not $mgr) { L 'ERROR: no tethering manager'; exit 1 }

$cfg = $mgr.GetCurrentAccessPointConfiguration()
$cfg.Ssid = $ssid
$cfg.Passphrase = $pass
$cfg.Band = Get-MobileHotspot2GhzBandValue
L "Applying SSID=$ssid Passphrase=$pass Band=2.4..."

$okCfg = $false
1..3 | ForEach-Object {
    $op = $mgr.ConfigureAccessPointAsync($cfg)
    if (Wait-WinRtAsync $op "ConfigureAP$_" 90) { $okCfg = $true; L "ConfigureAP OK on try $_"; break }
    Start-Sleep -Seconds 3
    $mgr = Get-TetheringManager
    $cfg = $mgr.GetCurrentAccessPointConfiguration()
    $cfg.Ssid = $ssid
    $cfg.Passphrase = $pass
    $cfg.Band = Get-MobileHotspot2GhzBandValue
}
if (-not $okCfg) { L 'WARN: ConfigureAP failed all tries - password may not stick' }

$okStart = $false
1..3 | ForEach-Object {
    $op2 = $mgr.StartTetheringAsync()
    if (Wait-WinRtAsync $op2 "Start$_" 90) { $okStart = $true; L "StartTethering OK on try $_"; break }
    Start-Sleep -Seconds 5
    $mgr = Get-TetheringManager
}
Start-Sleep -Seconds 12

$mgrF = Get-TetheringManager
$verify = $mgrF.GetCurrentAccessPointConfiguration()
L "VERIFY SSID=$($verify.Ssid)"
L "VERIFY pass matches: $($verify.Passphrase -eq $pass)"
L "VERIFY pass length: $($verify.Passphrase.Length)"
if ($verify.Passphrase -ne $pass) {
    L "ACTUAL PASSWORD ON PC: $($verify.Passphrase)"
}
L "State=$($mgrF.TetheringOperationalState) band=$(Get-MobileHotspotApBandLabel $mgrF)"
L "Gateway=$(Test-MobileHotspotGateway) DHCP=$(Test-HotspotDhcpListening)"

$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
Enable-EthernetHotspotIcs -Quiet | Out-Null
Ensure-HotspotDhcpFirewall
L "ICS=$(Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)"

L ''
L 'Use EXACTLY:'
L "  SSID: $ssid"
L "  Password: $pass"
L '  Type password manually - do not use saved/old osps password'
L '  Settings -> Mobile hotspot must show same password'
