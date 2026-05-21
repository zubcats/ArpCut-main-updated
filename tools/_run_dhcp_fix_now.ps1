# One-shot: PS5 DHCP fix (IPv4 + ICS + hotspot refresh)
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_ps5_dhcp_fix_run.txt'
function L($m) { $m | Tee-Object -FilePath $log -Append }

'' | Set-Content $log
L "=== PS5 DHCP fix run $(Get-Date -Format o) ==="

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
. (Join-Path $PSScriptRoot '_winrt_await.ps1')

# Wi-Fi radio ON (USB dongle — never disable adapter)
$wifi = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.InterfaceDescription -match 'Wireless LAN|802\.11|Wi-Fi' -and
    $_.InterfaceDescription -notmatch 'Direct|Hosted|Virtual'
} | Select-Object -First 1
if ($wifi) {
    if ($wifi.Status -eq 'Disabled') {
        L "Enabling Wi-Fi adapter $($wifi.Name)..."
        Enable-NetAdapter -Name $wifi.Name -Confirm:$false -EA SilentlyContinue
        Start-Sleep 5
    }
    $wlan = netsh wlan show interfaces 2>$null | Out-String
    if ($wlan -match 'State\s*:\s*connected') {
        L "Disconnecting PC from router Wi-Fi..."
        netsh wlan disconnect interface="$($wifi.Name)" 2>$null | Out-Null
        Start-Sleep 3
    }
    Set-NetIPInterface -InterfaceIndex $wifi.ifIndex -AddressFamily IPv4 -InterfaceMetric 8000 -EA SilentlyContinue
    L "Wi-Fi: $($wifi.Name) enabled, not router client"
}

# IPv4-only on hotspot NIC (PS5 stuck without IP when IPv6-only)
$ipv4Fix = Join-Path $PSScriptRoot '_fix_hotspot_ipv4.ps1'
if (Test-Path $ipv4Fix) {
    L '--- IPv4 hotspot fix ---'
    & $ipv4Fix 2>&1 | ForEach-Object { L $_ }
}

# DHCP + ICS refresh
$dhcpFix = Join-Path $PSScriptRoot '_fix_ps5_dhcp_now.ps1'
if (Test-Path $dhcpFix) {
    L '--- DHCP / ICS refresh ---'
    & $dhcpFix 2>&1 | ForEach-Object { L $_ }
}

L '--- Final status ---'
$s = Test-Ps5HotspotReady
L "  Gateway: $($s.Gateway)  DHCP: $($s.Dhcp)  ICS: $($s.IcsSharing)  Ready: $($s.Ready)"
L "  Hotspot: $($s.HotspotAdapter)  Ethernet: $($s.Ethernet)"

$ap = Get-HotspotPrivateAdapter
if ($ap) {
    $v6 = Get-NetAdapterBinding -Name $ap.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
    L "  IPv6 binding on hotspot: $($v6.Enabled)"
    Get-NetIPAddress -InterfaceIndex $ap.ifIndex -EA SilentlyContinue |
        Format-Table AddressFamily, IPAddress, PrefixLength -AutoSize |
        Out-String | ForEach-Object { L $_.TrimEnd() }
}

Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue |
    Format-Table LocalAddress, OwningProcess -AutoSize |
    Out-String | ForEach-Object { L $_.TrimEnd() }

L '=== On PS5: Forget osps -> restart console -> connect -> wait 2 min ==='
