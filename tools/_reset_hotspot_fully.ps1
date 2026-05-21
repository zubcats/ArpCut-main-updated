# Full mobile hotspot reset when NO device can connect (phone or PS5).
$log = Join-Path $PSScriptRoot '_reset_hotspot_fully.log'
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
L "=== Full hotspot reset $(Get-Date -Format o) ==="

Disconnect-WifiClientForEthernetHotspot | Out-Null

# 1) Stop hotspot + services
$mgr = Get-TetheringManager
if ($mgr -and $mgr.TetheringOperationalState.ToString() -eq 'On') {
    L 'Stopping hotspot...'
    Stop-MobileHotspotIfOn | Out-Null
    Start-Sleep -Seconds 8
}
L 'Restarting WlanSvc + icssvc + SharedAccess...'
Restart-Service WlanSvc -Force -EA SilentlyContinue
Start-Sleep -Seconds 4
Restart-Service icssvc -Force -EA SilentlyContinue
Start-Sleep -Seconds 3
Restart-Service SharedAccess -Force -EA SilentlyContinue
Start-Sleep -Seconds 4

# 2) Brief Wi-Fi radio reset (Realtek USB — re-enable immediately)
$wifi = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Wireless LAN|802\.11' -and $_.InterfaceDescription -notmatch 'Direct|Hosted|Virtual'
} | Select-Object -First 1
if ($wifi) {
    L "Reset radio: $($wifi.Name)..."
    Disable-NetAdapter -Name $wifi.Name -Confirm:$false -EA SilentlyContinue
    Start-Sleep -Seconds 6
    Enable-NetAdapter -Name $wifi.Name -Confirm:$false -EA SilentlyContinue
    Start-Sleep -Seconds 8
    L "Wi-Fi adapter: $((Get-NetAdapter -Name $wifi.Name).Status)"
}

# 3) Force 2.4 GHz + DHCP registry
Set-MobileHotspotBandRegistry2Ghz | Out-Null
$sa = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
foreach ($n in @('ScopeAddress', 'ScopeAddressBackup', 'StandaloneDhcpAddress')) {
    Set-ItemProperty -Path $sa -Name $n -Value '192.168.137.1' -Type String -Force -EA SilentlyContinue
}
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings' -Name TetheringBand -Value 1 -Type DWord -Force -EA SilentlyContinue
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings' -Name WiFiBand -Value 1 -Type DWord -Force -EA SilentlyContinue
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings' -Name PreferredBand -Value 1 -Type DWord -Force -EA SilentlyContinue

# 4) Reconfigure AP (keep SSID osps, ensure passphrase exists)
$mgr = Get-TetheringManager
if (-not $mgr) {
    L 'ERROR: No tethering manager - check Ethernet internet is up'
    exit 1
}
$cfg = $mgr.GetCurrentAccessPointConfiguration()
if (-not $cfg.Ssid -or $cfg.Ssid.Length -lt 1) { $cfg.Ssid = 'osps' }
if (-not $cfg.Passphrase -or $cfg.Passphrase.Length -lt 8) {
    $cfg.Passphrase = 'osps2024!'
    L 'Set hotspot password to: osps2024!  (change in Settings if you want)'
} else {
    $p = $cfg.Passphrase
    L "SSID=$($cfg.Ssid) password length=$($p.Length) ends with: $($p.Substring([Math]::Max(0,$p.Length-2)))"
}
$cfg.Band = Get-MobileHotspot2GhzBandValue
L 'Configuring AP 2.4 GHz...'
$null = Wait-WinRtAsync ($mgr.ConfigureAccessPointAsync($cfg)) 'ConfigureAP' 60
Start-Sleep -Seconds 3

L 'Starting hotspot...'
$null = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'Start' 60
Start-Sleep -Seconds 12

$mgr2 = Get-TetheringManager
L "State: $($mgr2.TetheringOperationalState) band=$(Get-MobileHotspotApBandLabel $mgr2)"
L "Gateway: $(Test-MobileHotspotGateway) DHCP67: $(Test-HotspotDhcpListening)"

$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
Enable-EthernetHotspotIcs -Quiet -ManualIcsOnly | Out-Null
if (-not (Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)) {
    L 'Applying ICS Ethernet -> hotspot...'
    Enable-EthernetHotspotIcs -Quiet | Out-Null
}
Ensure-HotspotDhcpFirewall
L "ICS: $(Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap)"

if (-not $cfg.Passphrase -or $cfg.Passphrase -eq 'osps2024!') {
    L ''
    L 'CONNECT WITH PASSWORD: osps2024!'
    L '(Settings -> Mobile hotspot shows the password)'
}
L ''
L 'On phone/PS5: forget osps, connect again with password above.'
