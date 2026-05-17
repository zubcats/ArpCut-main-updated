# Repair Mobile Hotspot / ICS after a broken ZubCut Clumsy mode attempt.
# Right-click -> Run as administrator (required).
$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run this script as Administrator (right-click -> Run as administrator).'
    exit 1
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

if ($mobileHotspotActive -and $snapshot.Count -eq 0) {
    Write-Host 'Mobile Hotspot is active — skipping ICS reset (clearing it breaks client DHCP).'
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
