# Repair Mobile Hotspot / ICS after a broken ZubCut Clumsy mode attempt.
# Right-click -> Run as administrator (required).
$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run this script as Administrator (right-click -> Run as administrator).'
    exit 1
}

$repairWd = Join-Path $PSScriptRoot '_repair_windivert_service.ps1'
if (Test-Path $repairWd) {
    Write-Host '--- WinDivert driver service (fixes Kill error code 3) ---'
    & $repairWd
}

$statePath = Join-Path $env:APPDATA 'ZubCut\clumsy_ics_state.json'
$snapshot = @()
if (Test-Path $statePath) {
    try {
        $saved = Get-Content -Raw -Path $statePath | ConvertFrom-Json
        if ($saved.snapshot) { $snapshot = @($saved.snapshot) }
    } catch {}
}

function NormGuid([object]$g) {
    if ($null -eq $g) { return '' }
    return ($g.ToString().Trim('{', '}').ToLowerInvariant())
}

function Ensure-WlanAutoConfigHealthy {
    $fixed = $false
    try {
        $wl = Get-Service -Name WlanSvc -ErrorAction Stop
        if ($wl.Status -eq 'Running' -and $wl.StartType -in @('Automatic', 'AutomaticDelayedStart')) {
            return $false
        }
        if ($wl.StartType -notin @('Automatic', 'AutomaticDelayedStart')) {
            Set-Service -Name WlanSvc -StartupType Automatic -ErrorAction SilentlyContinue
            $fixed = $true
        }
        if ($wl.Status -ne 'Running') {
            Start-Service -Name WlanSvc -ErrorAction SilentlyContinue
            $fixed = $true
        }
    } catch {
        try { Set-Service -Name WlanSvc -StartupType Automatic -ErrorAction SilentlyContinue } catch {}
        try {
            $wl2 = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
            if ($null -eq $wl2 -or $wl2.Status -ne 'Running') {
                Start-Service -Name WlanSvc -ErrorAction SilentlyContinue
            }
        } catch {}
        $fixed = $true
    }
    return $fixed
}

function Ensure-SharingServicesLight {
    foreach ($svc in @('SharedAccess', 'icssvc', 'RemoteAccess')) {
        try {
            $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
            if ($null -ne $s -and $s.Status -ne 'Running') {
                Start-Service -Name $svc -ErrorAction SilentlyContinue
            }
        } catch {}
    }
}

Write-Host 'Starting sharing services if stopped (does not restart the Wi-Fi connection manager)...'
Ensure-SharingServicesLight
Start-Sleep -Seconds 1

$mobileHotspotActive = $false
try {
    $mobileHotspotActive = [bool](Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1)
} catch {}

# Never wipe ICS while the hotspot gateway is up — PS5 shows "connected" but gets no IP/internet.
if ($mobileHotspotActive) {
    Write-Host 'Mobile Hotspot is active — skipping ICS reset (wiping breaks PS5 DHCP).'
} else {
    Write-Host 'Clearing Internet Connection Sharing on all adapters...'
    $share = New-Object -ComObject HNetCfg.HNetShare
    $connMap = @{}
    foreach ($conn in @($share.EnumEveryConnection())) {
        try {
            $props = $share.NetConnectionProps($conn)
            $guid = NormGuid($props.Guid)
            $cfg = $share.INetSharingConfigurationForINetConnection($conn)
            $connMap[$guid] = $cfg
        } catch { continue }
    }
    foreach ($cfg in $connMap.Values) {
        try { if ($cfg.SharingEnabled) { $cfg.DisableSharing() } } catch {}
    }
    Start-Sleep -Milliseconds 800

    if ($snapshot.Count -gt 0) {
        Write-Host 'Restoring saved sharing snapshot...'
        foreach ($row in $snapshot) {
            $g = NormGuid($row.guid)
            if (-not $connMap.ContainsKey($g)) { continue }
            try {
                $kind = [int]$row.type
                if ($kind -eq 0 -or $kind -eq 1) { $connMap[$g].EnableSharing($kind) }
            } catch {}
        }
    }
}

# Re-enable IPv6 on hotspot NIC, remove APIPA, ensure gateway (undo bad IPv6-disable scripts).
$down = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection')
} | Select-Object -First 1
if ($down) {
    $v6 = Get-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -ErrorAction SilentlyContinue
    if ($v6 -and -not $v6.Enabled) {
        Enable-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -ErrorAction SilentlyContinue
        Write-Host "Re-enabled IPv6 on $($down.Name)"
    }
    Get-NetIPAddress -InterfaceIndex $down.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -like '169.254.*' } |
        ForEach-Object {
            Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -ErrorAction SilentlyContinue
        }
    if (-not (Get-NetIPAddress -InterfaceIndex $down.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -eq '192.168.137.1' })) {
        New-NetIPAddress -InterfaceIndex $down.ifIndex -IPAddress 192.168.137.1 -PrefixLength 24 -ErrorAction SilentlyContinue | Out-Null
    }
    foreach ($line in @(arp -a)) {
        if ($line -match '(192\.168\.137\.\d+)\s+([0-9a-fA-F\-]+)\s+static' -and $Matches[1] -ne '192.168.137.1' -and $Matches[1] -ne '192.168.137.255') {
            arp -d $Matches[1] 2>$null | Out-Null
        }
    }
}

$saParams = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
foreach ($n in @('ScopeAddress', 'ScopeAddressBackup', 'StandaloneDhcpAddress')) {
    Set-ItemProperty -Path $saParams -Name $n -Value '192.168.137.1' -Type String -Force -ErrorAction SilentlyContinue
}

# Wi-Fi public -> hotspot private if missing
$up = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and ($_.Name -eq 'Wi-Fi' -or $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi')
    $_.InterfaceDescription -notmatch 'Direct|Virtual|Bluetooth'
} | Select-Object -First 1
if ($up -and $down) {
    $share2 = New-Object -ComObject HNetCfg.HNetShare
    $cm = @{}
    foreach ($conn in @($share2.EnumEveryConnection())) {
        try {
            $p = $share2.NetConnectionProps($conn)
            $cm[(NormGuid $p.Guid)] = $share2.INetSharingConfigurationForINetConnection($conn)
        } catch {}
    }
    $upG = NormGuid $up.InterfaceGuid
    $dnG = NormGuid $down.InterfaceGuid
    if ($cm.ContainsKey($upG) -and $cm.ContainsKey($dnG)) {
        $uc = $cm[$upG]; $dc = $cm[$dnG]
        $icsOk = $false
        try {
            $icsOk = $uc.SharingEnabled -and $dc.SharingEnabled -and [int]$uc.SharingConnectionType -eq 0 -and [int]$dc.SharingConnectionType -eq 1
        } catch {}
        if (-not $icsOk) {
            Write-Host 'Applying Wi-Fi -> hotspot internet sharing...'
            foreach ($k in $cm.Keys) {
                try { if ($cm[$k].SharingEnabled) { $cm[$k].DisableSharing() } } catch {}
            }
            Start-Sleep -Seconds 1
            try {
                $cm[$upG].EnableSharing(0)
                $cm[$dnG].EnableSharing(1)
            } catch {}
            Start-Sleep -Seconds 3
        }
    }
}

$dhcp67 = [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue)
$gw137 = [bool](Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' })
Write-Host ''
Write-Host "Gateway 192.168.137.1: $gw137"
Write-Host "DHCP listening (UDP 67): $dhcp67"

Write-Host 'Re-enabling disabled Wi-Fi / hotspot adapters...'
Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {
    $d = ($_.Name + ' ' + $_.InterfaceDescription)
    if ($_.Status -eq 'Disabled' -and ($d -match 'Wi-Fi|Wireless|Wi-Fi Direct|Hosted')) {
        try { Enable-NetAdapter -Name $_.Name -Confirm:$false -ErrorAction SilentlyContinue } catch {}
    }
}

Remove-Item -Path $statePath -Force -ErrorAction SilentlyContinue

Ensure-WlanAutoConfigHealthy | Out-Null
$wlCheck = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
if ($null -eq $wlCheck -or $wlCheck.Status -ne 'Running' -or $wlCheck.StartType -eq 'Manual' -or $wlCheck.StartType -eq 'Disabled') {
    Write-Host ''
    Write-Host 'ERROR: WLAN AutoConfig (WlanSvc) is still not running.'
    Write-Host 'Open services.msc -> WLAN AutoConfig -> Startup type Automatic -> Start -> reboot.'
    exit 1
}

Write-Host ''
Write-Host 'Done. Now manually:'
Write-Host '  1. Settings -> Network -> Mobile hotspot -> OFF'
Write-Host '  2. Wait 10 seconds'
Write-Host '  3. Mobile hotspot -> ON'
Write-Host '  4. Connect PS5 to the PC hotspot Wi-Fi (not the router)'
Write-Host ''
Write-Host 'In ZubCut: turn Clumsy mode OFF, install the latest build, then use'
Write-Host '  Console connects via -> PC Mobile Hotspot before enabling Clumsy again.'
