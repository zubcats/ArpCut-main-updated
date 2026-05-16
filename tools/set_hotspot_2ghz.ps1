# Force Mobile Hotspot to 2.4 GHz (when Settings has no band option).
$ErrorActionPreference = 'Continue'
Write-Host '=== Set hotspot to 2.4 GHz ==='

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator'
    Read-Host 'Press Enter'
    exit 1
}

# Registry (works on some builds)
$regPaths = @(
    'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings',
    'HKCU:\Software\Microsoft\WCM\Tethering\Settings'
)
foreach ($rp in $regPaths) {
    if (-not (Test-Path $rp)) {
        try { New-Item -Path $rp -Force | Out-Null } catch {}
    }
    foreach ($name in @('TetheringBand', 'WiFiBand', 'PreferredBand')) {
        try {
            Set-ItemProperty -Path $rp -Name $name -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue
            Write-Host "Set $rp\$name = 1 (2.4 GHz)"
        } catch {}
    }
}

# WinRT API (preferred when available)
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringWiFiBand, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]

    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if (-not $profile) { throw 'PC not connected to internet (Wi-Fi).' }

    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
    $wasOn = ($mgr.TetheringOperationalState.ToString() -eq 'On')
    if ($wasOn) {
        Write-Host 'Stopping hotspot...'
        $stop = $mgr.StopTetheringAsync()
        $deadline = (Get-Date).AddSeconds(20)
        while ([int]$stop.Status -eq 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    }

    $cfg = $mgr.GetCurrentAccessPointConfiguration()
    if (-not $cfg.Ssid) { $cfg.Ssid = 'osps' }
    if (-not $cfg.Passphrase) { $cfg.Passphrase = 'Blacklist67' }
    $cfg.Band = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringWiFiBand]::TwoPointFourGigahertz
    Write-Host "Configuring SSID=$($cfg.Ssid) Band=2.4GHz..."

    $conf = $mgr.ConfigureAccessPointAsync($cfg)
    $deadline = (Get-Date).AddSeconds(25)
    while ([int]$conf.Status -eq 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    if ([int]$conf.Status -eq 1) {
        $r = $conf.GetResults()
        Write-Host "ConfigureAccessPoint: $r"
    } else {
        Write-Host "ConfigureAccessPoint status=$($conf.Status)"
    }

    Write-Host 'Starting hotspot...'
    $start = $mgr.StartTetheringAsync()
    $deadline = (Get-Date).AddSeconds(25)
    while ([int]$start.Status -eq 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    if ([int]$start.Status -eq 1) { Write-Host "StartTethering: $($start.GetResults())" }

    $mgr2 = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
    Write-Host "Now: State=$($mgr2.TetheringOperationalState) Band=$($mgr2.Configuration.Band) SSID=$($mgr2.Configuration.SsidPrefix)"
} catch {
    Write-Host "API: $($_.Exception.Message)"
}

Write-Host ''
Write-Host 'Toggle hotspot OFF/ON in Settings if PS5 still cannot see osps.'
Write-Host 'If no 2.4 GHz option exists, move PS5 within 3 feet of the USB Wi-Fi dongle.'
Read-Host 'Press Enter'
