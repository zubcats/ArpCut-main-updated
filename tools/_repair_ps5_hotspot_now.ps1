# Undo IPv6-disable regression + clear stale ARP + refresh hotspot (Admin)
$ErrorActionPreference = 'Continue'
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host 'Elevating...'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

Write-Host '=== PS5 hotspot repair ==='
$down = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection')
} | Select-Object -First 1
if (-not $down) {
    Write-Host 'Starting hotspot...'
    & (Join-Path $PSScriptRoot '_run_hotspot_turn_on_fix.ps1')
    $down = Get-NetAdapter -EA SilentlyContinue | Where-Object {
        $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection')
    } | Select-Object -First 1
}
if ($down) {
    Write-Host "Adapter: $($down.Name)"
    $v6 = Get-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
    if ($v6 -and -not $v6.Enabled) {
        Enable-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6
        Write-Host 'Re-enabled IPv6 binding on hotspot'
    }
    Get-NetIPAddress -InterfaceIndex $down.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |
        Where-Object { $_.IPAddress -like '169.254.*' } |
        ForEach-Object {
            Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -EA SilentlyContinue
            Write-Host "Removed APIPA $($_.IPAddress)"
        }
}
foreach ($line in @(arp -a)) {
    if ($line -match '(192\.168\.137\.\d+)\s+([0-9a-fA-F\-]+)\s+static') {
        arp -d $Matches[1] 2>$null | Out-Null
        Write-Host "Cleared static ARP $($Matches[1])"
    }
}
$repo = Split-Path $PSScriptRoot -Parent
$py = @('py', 'python', 'python3') | ForEach-Object {
    $c = Get-Command $_ -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { $c.Source; break }
}
if ($py) {
    & $py -c "import sys; sys.path.insert(0, r'$repo'); from src.tools.clumsy_ics import repair_clumsy_network_sharing; print(repair_clumsy_network_sharing())"
}
Write-Host ''
Write-Host "gw137: $([bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object IPAddress -eq '192.168.137.1'))"
Write-Host "dhcp67: $([bool](Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue))"
if ($down) {
    $v6 = Get-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
    Write-Host "IPv6 on hotspot: $($v6.Enabled)"
}
Write-Host 'Forget hotspot on PS5, reconnect now.'
