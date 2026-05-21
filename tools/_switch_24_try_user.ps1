$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root '_hotspot_2ghz_apply.ps1')
$log = Join-Path $root '_switch_24ghz_result.txt'
"=== $(Get-Date) user=$([Security.Principal.WindowsIdentity]::GetCurrent().Name) admin=$(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) ===" | Out-File $log
$iface = 'Wi-Fi'
$ssid = 'Wifi1'
netsh wlan disconnect interface="$iface" 2>&1 | Out-File $log -Append
Start-Sleep -Seconds 5
$t = Find-BssidForSsidBand -Ssid $ssid -Band '2.4'
if (-not $t) { "NO_24_BSSID" | Out-File $log -Append; exit 1 }
"TARGET=$($t.Bssid)" | Out-File $log -Append
netsh wlan connect name="$ssid" ssid="$ssid" interface="$iface" bss="$($t.Bssid)" 2>&1 | Out-File $log -Append
Start-Sleep -Seconds 15
"CHANNEL=$(Get-WifiUplinkChannel)" | Out-File $log -Append
netsh wlan show interfaces | Out-File $log -Append
