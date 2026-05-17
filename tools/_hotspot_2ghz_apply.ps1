# Shared 2.4 GHz hotspot logic (used by set_hotspot_2ghz.ps1 and _run_hotspot_2ghz_now.ps1).
. (Join-Path $PSScriptRoot '_winrt_await.ps1')

function Ensure-TetheringWinRTLoaded {
    try {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction SilentlyContinue
        [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
        [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
        return $true
    } catch {
        return $false
    }
}

function Get-TetheringManager {
    try {
        if (-not (Ensure-TetheringWinRTLoaded)) { return $null }
        $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
        if (-not $profile) { return $null }
        return [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
    } catch {
        return $null
    }
}

function Set-MobileHotspotBandRegistry2Ghz {
    foreach ($rp in @(
        'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings',
        'HKCU:\Software\Microsoft\WCM\Tethering\Settings'
    )) {
        if (-not (Test-Path $rp)) {
            try { New-Item -Path $rp -Force | Out-Null } catch {}
        }
        foreach ($name in @('TetheringBand', 'WiFiBand', 'PreferredBand')) {
            try {
                Set-ItemProperty -Path $rp -Name $name -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue
            } catch {}
        }
    }
}

function Get-MobileHotspotBandLabel([object]$mgr) {
    if ($null -eq $mgr) { return '' }
    try {
        $ap = $mgr.GetCurrentAccessPointConfiguration()
        if ($ap -and $ap.Band) { return [string]$ap.Band }
    } catch {}
    try { return [string]$mgr.Configuration.Band } catch {}
    return ''
}
function Test-MobileHotspotBandNeeds2Ghz([object]$mgr) {
    if ($null -eq $mgr) { return $true }
    $b = Get-MobileHotspotBandLabel $mgr
    if ($b -match 'TwoPointFour') { return $false }
    return $true
}

function Get-MobileHotspot2GhzBandValue {
    if (-not (Ensure-TetheringWinRTLoaded)) { return 1 }
    try {
        return [Windows.Networking.NetworkOperators.NetworkOperatorTetheringWiFiBand]::TwoPointFourGigahertz
    } catch {
        return 1
    }
}

function Stop-MobileHotspotIfOn {
    $mgr = Get-TetheringManager
    if ($null -eq $mgr) { return $false }
    if ($mgr.TetheringOperationalState.ToString() -ne 'On') { return $true }
    $op = $mgr.StopTetheringAsync()
    if (-not (Wait-WinRtAsync $op 'StopTethering' 30)) { return $false }
    Start-Sleep -Seconds 3
    return $true
}

function Configure-MobileHotspotAccessPoint2Ghz([object]$mgr, [bool]$restartIfOn) {
    if ($null -eq $mgr) { return $false }
    if (-not (Ensure-TetheringWinRTLoaded)) { return $false }
    $band2Ghz = Get-MobileHotspot2GhzBandValue
    $needRestart = $false
    if (($mgr.TetheringOperationalState.ToString() -eq 'On') -and $restartIfOn) {
        if (-not (Stop-MobileHotspotIfOn)) { return $false }
        Start-Sleep -Seconds 2
        $needRestart = $true
        $mgr = Get-TetheringManager
        if ($null -eq $mgr) { return $false }
    }
    $cfg = $mgr.GetCurrentAccessPointConfiguration()
    if ($null -eq $cfg) { return $false }
    if ([string]$cfg.Band -notmatch 'TwoPointFour') {
        $cfg.Band = $band2Ghz
        $op = $mgr.ConfigureAccessPointAsync($cfg)
        if (-not (Wait-WinRtAsync $op 'ConfigureAccessPoint' 30)) { return $false }
    }
    if ($needRestart) {
        $op2 = $mgr.StartTetheringAsync()
        if (-not (Wait-WinRtAsync $op2 'StartTethering' 40)) { return $false }
        Start-Sleep -Seconds 4
    }
    return $true
}

function Get-WifiUplinkChannel {
    $out = netsh wlan show interfaces 2>$null | Out-String
    if ($out -match 'Channel\s*:\s*(\d+)') { return [int]$Matches[1] }
    return 0
}
function Move-UplinkWifiTo24GhzIfNeeded {
    $ch = Get-WifiUplinkChannel
    if ($ch -ge 1 -and $ch -le 14) { return $true }
    $ifaces = netsh wlan show interfaces 2>$null | Out-String
    if ($ifaces -notmatch 'SSID\s*:\s*(.+)\r?\n') { return $false }
    $ssid = $Matches[1].Trim()
    if (-not $ssid) { return $false }
    $scan = netsh wlan show networks mode=bssid 2>$null | Out-String
    $blocks = $scan -split '(?=SSID\s+\d+\s*:)'
    $ssidPat = [regex]::Escape($ssid)
    $bestBssid = $null
    $bestSignal = -1
    foreach ($block in $blocks) {
        if ($block -notmatch "SSID\s*(?:\d+\s*)?:\s*$ssidPat") { continue }
        foreach ($part in ($block -split 'BSSID \d+\s*:')) {
            if ($part -notmatch '([0-9a-f]{2}(?::[0-9a-f]{2}){5})') { continue }
            $bssid = $Matches[1]
            $chB = 0; $sig = 0
            if ($part -match 'Channel\s*:\s*(\d+)') { $chB = [int]$Matches[1] }
            if ($part -match 'Signal\s*:\s*(\d+)') { $sig = [int]$Matches[1] }
            if ($chB -ge 1 -and $chB -le 14 -and $sig -gt $bestSignal) {
                $bestBssid = $bssid
                $bestSignal = $sig
            }
        }
    }
    if (-not $bestBssid) { return $false }
    $iface = 'Wi-Fi'
    try {
        $wa = Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Wireless LAN' -and $_.Status -eq 'Up' } | Select-Object -First 1
        if ($wa) { $iface = $wa.Name }
    } catch {}
    Stop-MobileHotspotIfOn | Out-Null
    Start-Sleep -Seconds 2
    netsh wlan disconnect interface="$iface" 2>$null | Out-Null
    Start-Sleep -Seconds 2
    netsh wlan connect name="$ssid" ssid="$ssid" interface="$iface" bss="$bestBssid" 2>$null | Out-Null
    Start-Sleep -Seconds 8
    $ch2 = Get-WifiUplinkChannel
    return ($ch2 -ge 1 -and $ch2 -le 14)
}
function Ensure-MobileHotspot2GhzBand {
    # Hotspot AP only — does not move PC Wi-Fi uplink off 5 GHz.
    Set-MobileHotspotBandRegistry2Ghz | Out-Null
    if (-not (Ensure-TetheringWinRTLoaded)) { return $false }
    $mgr = Get-TetheringManager
    if ($null -eq $mgr) { return $false }
    if (-not (Test-MobileHotspotBandNeeds2Ghz $mgr)) { return $true }
    $restart = ($mgr.TetheringOperationalState.ToString() -eq 'On')
    return (Configure-MobileHotspotAccessPoint2Ghz $mgr $restart)
}

function Test-EthernetInternetUplink {
    try {
        $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
            Sort-Object RouteMetric, InterfaceMetric
        foreach ($rt in @($routes)) {
            $if = Get-NetAdapter -InterfaceIndex $rt.InterfaceIndex -ErrorAction SilentlyContinue
            if ($null -eq $if -or $if.Status -ne 'Up') { continue }
            $d = ($if.Name + ' ' + $if.InterfaceDescription)
            if ($d -match 'Ethernet|Gigabit|GbE|LAN' -and $d -notmatch 'Virtual|Bluetooth|Direct') {
                return $true
            }
        }
    } catch {}
    return $false
}

function Find-BssidForSsidBand {
    param(
        [string]$Ssid,
        [ValidateSet('2.4', '5')]
        [string]$Band
    )
    if (-not $Ssid) { return $null }
    $scan = netsh wlan show networks mode=bssid 2>$null | Out-String
    $blocks = $scan -split '(?=SSID\s+\d+\s*:)'
    $ssidPat = [regex]::Escape($Ssid)
    $bestBssid = $null
    $bestSignal = -1
    foreach ($block in $blocks) {
        if ($block -notmatch "SSID\s*(?:\d+\s*)?:\s*$ssidPat") { continue }
        foreach ($part in ($block -split 'BSSID \d+\s*:')) {
            if ($part -notmatch '([0-9a-f]{2}(?::[0-9a-f]{2}){5})') { continue }
            $bssid = $Matches[1]
            $chB = 0; $sig = 0
            if ($part -match 'Channel\s*:\s*(\d+)') { $chB = [int]$Matches[1] }
            if ($part -match 'Signal\s*:\s*(\d+)') { $sig = [int]$Matches[1] }
            $is24 = ($chB -ge 1 -and $chB -le 14)
            $is5 = ($chB -gt 14)
            if ($Band -eq '2.4' -and -not $is24) { continue }
            if ($Band -eq '5' -and -not $is5) { continue }
            if ($sig -gt $bestSignal) {
                $bestBssid = $bssid
                $bestSignal = $sig
            }
        }
    }
    if ($bestBssid) { return @{ Ssid = $Ssid; Bssid = $bestBssid } }
    return $null
}

function Get-WifiClientInterfaceName {
    $wa = Get-NetAdapter -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceDescription -match 'Wireless LAN' -and $_.Status -eq 'Up' } |
        Select-Object -First 1
    if ($wa) { return $wa.Name }
    return 'Wi-Fi'
}

function Connect-WifiUplinkTo5Ghz {
    # Hotspot must be off on single-radio USB before the client can rejoin 5 GHz.
    Stop-MobileHotspotIfOn | Out-Null
    Start-Sleep -Seconds 2
    $ifaces = netsh wlan show interfaces 2>$null | Out-String
    $ssid = $null
    if ($ifaces -match 'SSID\s*:\s*(.+)\r?\n') { $ssid = $Matches[1].Trim() }
    if (-not $ssid) {
        $prof = netsh wlan show profiles 2>$null | Out-String
        if ($prof -match 'All User Profile\s*:\s*(.+)\r?\n') { $ssid = $Matches[1].Trim() }
    }
    if (-not $ssid) { return $false }
    $target = Find-BssidForSsidBand -Ssid $ssid -Band '5'
    if (-not $target) { return $false }
    $iface = Get-WifiClientInterfaceName
    netsh wlan disconnect interface="$iface" 2>$null | Out-Null
    Start-Sleep -Seconds 2
    netsh wlan connect name="$($target.Ssid)" ssid="$($target.Ssid)" interface="$iface" bss="$($target.Bssid)" 2>$null | Out-Null
    Start-Sleep -Seconds 8
    $ch = Get-WifiUplinkChannel
    return ($ch -gt 14)
}

function Start-MobileHotspotAfter2GhzConfig {
    $mgr = Get-TetheringManager
    if ($null -eq $mgr) { return $false }
    if ($mgr.TetheringOperationalState.ToString() -eq 'On') { return $true }
    $op = $mgr.StartTetheringAsync()
    if (-not (Wait-WinRtAsync $op 'StartTethering' 40)) { return $false }
    Start-Sleep -Seconds 5
    return $true
}
