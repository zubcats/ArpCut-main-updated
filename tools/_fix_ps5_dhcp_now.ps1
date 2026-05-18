# Fix PS5 "cannot obtain IP" — DHCP + ICS on Ethernet -> hotspot (Admin).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_ps5_dhcp_fix_log.txt'
function L([string]$m) { Write-Host $m; Add-Content $log $m -Encoding utf8 -ErrorAction SilentlyContinue }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    L 'Click Yes on UAC...'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
. (Join-Path $PSScriptRoot '_winrt_await.ps1')

'' | Set-Content $log -Force
L "=== PS5 DHCP fix $(Get-Date -Format o) ==="

# 1) Remove ZubCut kill firewall blocks (block PS5 / DHCP on hotspot subnet)
$removed = 0
$rules = netsh advfirewall firewall show rule name=all verbose 2>$null
$names = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($line in @($rules)) {
    if ($line -match '^\s*Rule Name:\s+(zubcut_ip_.+)$') {
        [void]$names.Add($Matches[1].Trim())
    }
}
foreach ($n in $names) {
    netsh advfirewall firewall delete rule name="$n" 2>$null | Out-Null
    L "Removed firewall block: $n"
    $removed++
}
L "Removed $removed ZubCut IP block rule(s)"

# 2) DHCP firewall (must allow 67/68 on hotspot subnet)
Ensure-HotspotDhcpFirewall
L 'ICS DHCP firewall rules applied'

# 3) DHCP registry scope for SharedAccess
Set-HotspotDhcpRegistry

# 4) Stale clumsy state
$zc = Join-Path $env:APPDATA 'ZubCut\clumsy_ics_state.json'
if (Test-Path $zc) { Remove-Item $zc -Force -ErrorAction SilentlyContinue; L 'Removed clumsy_ics_state.json' }

# 5) Hotspot OFF -> restart SharedAccess -> ON (refreshes DHCP server)
$mgr = Get-TetheringManager
if ($mgr) {
    L "Tethering before: $($mgr.TetheringOperationalState)"
    if ($mgr.TetheringOperationalState.ToString() -eq 'On') {
        L 'Hotspot OFF (refresh DHCP)...'
        $null = Wait-WinRtAsync ($mgr.StopTetheringAsync()) 'StopTethering' 45
        Start-Sleep -Seconds 12
    }
}
Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 6
if ($mgr) {
    L 'Hotspot ON...'
    $null = Wait-WinRtAsync ($mgr.StartTetheringAsync()) 'StartTethering' 60
    Start-Sleep -Seconds 12
    $mgr = Get-TetheringManager
    L "Tethering after: $($mgr.TetheringOperationalState)"
}

if (-not (Test-MobileHotspotGateway)) {
    L 'WARN: No 192.168.137.1 — turn Mobile hotspot ON in Settings, run this again.'
}

# 6) ICS: Ethernet (internet) -> hotspot (PS5), NOT Wi-Fi -> hotspot
$eth = Get-EthernetUplinkAdapter
$ap = Get-HotspotPrivateAdapter
if ($eth -and $ap) {
    L "ICS pair: $($eth.Name) -> $($ap.Name)"
    Enable-EthernetHotspotIcs -Quiet | Out-Null
} else {
    L "WARN: Could not find Ethernet + hotspot adapters for ICS"
}

# 7) Hotspot adapter cleanup
if ($ap) {
    Get-NetIPAddress -InterfaceIndex $ap.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -like '169.254.*' } |
        ForEach-Object {
            Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -ErrorAction SilentlyContinue
        }
}

L ''
L '=== RESULT ==='
$s = Show-Ps5HotspotStatus
L "  DHCP UDP 67: $($s.Dhcp)"
L "  192.168.137.1: $($s.Gateway)"
L "  ICS sharing: $($s.IcsSharing)"
L ''
L 'On PS5:'
L '  1. Settings -> Network -> your hotspot -> Forget / Delete'
L '  2. Restart PS5 (or turn Wi-Fi off 30 sec on)'
L '  3. Connect to osps again — wait up to 2 min for IP'
if ($s.Ready) {
    L 'SUCCESS: DHCP should work now.'
    exit 0
}
L 'If still failing: Settings -> Mobile hotspot OFF 20 sec ON, run this script again.'
exit 1
