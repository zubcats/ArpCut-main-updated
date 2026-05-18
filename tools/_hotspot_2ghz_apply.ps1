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
    return (Connect-WifiUplinkToBand -Band '2.4' -StopHotspotFirst)
}
function Restart-IcssvcIfNeeded {
    try {
        $s = Get-Service -Name icssvc -ErrorAction SilentlyContinue
        if ($null -ne $s -and $s.Status -eq 'Running') {
            Restart-Service -Name icssvc -Force -ErrorAction Stop
            Start-Sleep -Seconds 3
            return $true
        }
    } catch {}
    return $false
}

function Get-WifiClientStatePath {
    return (Join-Path $env:LOCALAPPDATA 'ZubCut\wifi-client-before-hotspot.json')
}

function Save-WifiClientStateForHotspot {
    $ssid = Get-WifiUplinkSsid
    if (-not $ssid) { return }
    $dir = Split-Path (Get-WifiClientStatePath) -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    (@{ ssid = $ssid; savedAt = (Get-Date).ToString('o') } | ConvertTo-Json) |
        Set-Content -Path (Get-WifiClientStatePath) -Encoding UTF8 -Force
}

function Restore-WifiClientAfterHotspot {
    $path = Get-WifiClientStatePath
    if (-not (Test-Path $path)) { return $false }
    try {
        $st = Get-Content $path -Raw | ConvertFrom-Json
        $ssid = [string]$st.ssid
        if (-not $ssid) { return $false }
        Remove-Item $path -Force -ErrorAction SilentlyContinue
        return (Connect-WifiUplinkToBand -Band '5' -StopHotspotFirst)
    } catch {
        return $false
    }
}

function Ensure-EthernetPreferredRouting {
    <#
    When Wi-Fi client and Ethernet both have 0.0.0.0/0, ICS NAT can break for hotspot clients.
    Prefer Ethernet for internet; deprioritize Wi-Fi client default route.
    #>
    $eth = Get-EthernetUplinkAdapter
    if (-not $eth) { return $false }
    try {
        Set-NetIPInterface -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -InterfaceMetric 10 -ErrorAction SilentlyContinue
    } catch {}
    foreach ($if in @(Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.ConnectionState -eq 'Connected' })) {
        $a = Get-NetAdapter -InterfaceIndex $if.InterfaceIndex -ErrorAction SilentlyContinue
        if (-not $a) { continue }
        $d = ($a.Name + ' ' + $a.InterfaceDescription)
        if ($d -match 'Wireless|Wi-Fi|WiFi|WLAN|802\.11') {
            if ($d -notmatch 'Direct|Hosted') {
                try {
                    Set-NetIPInterface -InterfaceIndex $if.InterfaceIndex -AddressFamily IPv4 -InterfaceMetric 5000 -ErrorAction SilentlyContinue
                } catch {}
            }
        }
    }
    return $true
}

function Disconnect-WifiClientForEthernetHotspot {
    <#
    Realtek USB: never disable the Wi-Fi adapter (kills hotspot). Disconnect router Wi-Fi only.
    With Ethernet internet, disconnect Wi-Fi client so the radio hosts hotspot on 2.4 GHz.
    #>
    if (-not (Test-EthernetInternetUplink)) { return $false }
    $wifi = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
        $_.InterfaceDescription -match 'Wireless LAN|802\.11|Wi-Fi' -and
        $_.InterfaceDescription -notmatch 'Direct|Hosted|Virtual'
    } | Select-Object -First 1
    if ($wifi -and $wifi.Status -eq 'Disabled') {
        Enable-NetAdapter -Name $wifi.Name -Confirm:$false -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }
    $iface = Get-WifiClientInterfaceName
    $out = netsh wlan show interfaces 2>$null | Out-String
    if ($out -notmatch 'State\s*:\s*connected') {
        if ($wifi) {
            Set-NetIPInterface -InterfaceIndex $wifi.ifIndex -AddressFamily IPv4 -InterfaceMetric 8000 -ErrorAction SilentlyContinue
        }
        return $true
    }
    Save-WifiClientStateForHotspot
    netsh wlan disconnect interface="$iface" 2>$null | Out-Null
    Start-Sleep -Seconds 3
    if ($wifi) {
        Set-NetIPInterface -InterfaceIndex $wifi.ifIndex -AddressFamily IPv4 -InterfaceMetric 8000 -ErrorAction SilentlyContinue
    }
    return $true
}

function Get-MobileHotspotApBandLabel([object]$mgr) {
    if ($null -eq $mgr) { return '' }
    try {
        $ap = $mgr.GetCurrentAccessPointConfiguration()
        if ($ap -and $ap.Band) { return [string]$ap.Band }
    } catch {}
    return Get-MobileHotspotBandLabel $mgr
}

function Force-MobileHotspot2Ghz {
    param(
        [switch]$DisconnectWifiClientIfEthernet,
        [switch]$KeepHotspotOn
    )
    if ($DisconnectWifiClientIfEthernet) {
        Disconnect-WifiClientForEthernetHotspot | Out-Null
    }

    if (-not $KeepHotspotOn) {
        Stop-MobileHotspotIfOn | Out-Null
        Start-Sleep -Seconds 4
    }
    Set-MobileHotspotBandRegistry2Ghz | Out-Null
    Restart-IcssvcIfNeeded | Out-Null
    Start-Sleep -Seconds 2

    if (-not (Ensure-TetheringWinRTLoaded)) { return $false }
    $mgr = Get-TetheringManager
    if ($null -eq $mgr) { return $false }

    if (-not (Configure-MobileHotspotAccessPoint2Ghz $mgr $false)) { return $false }
    if (-not (Start-MobileHotspotAfter2GhzConfig)) { return $false }

    $mgr2 = Get-TetheringManager
    $apBand = Get-MobileHotspotApBandLabel $mgr2
    if ($apBand -match 'TwoPointFour') { return $true }

    # Hard reset ICS / tethering and try once more.
    Stop-MobileHotspotIfOn | Out-Null
    try {
        Restart-Service -Name icssvc -Force -ErrorAction Stop
        Start-Sleep -Seconds 5
    } catch {}
    $mgr3 = Get-TetheringManager
    if ($null -eq $mgr3) { return $false }
    if (-not (Configure-MobileHotspotAccessPoint2Ghz $mgr3 $false)) { return $false }
    if (-not (Start-MobileHotspotAfter2GhzConfig)) { return $false }
    return ((Get-MobileHotspotApBandLabel (Get-TetheringManager)) -match 'TwoPointFour')
}

function Ensure-MobileHotspot2GhzBand {
    # Hotspot AP only — does not move PC Wi-Fi uplink off 5 GHz (use Ethernet for 5 GHz PC + 2.4 hotspot).
    Set-MobileHotspotBandRegistry2Ghz | Out-Null
    Restart-IcssvcIfNeeded | Out-Null
    if (-not (Ensure-TetheringWinRTLoaded)) { return $false }
    $mgr = Get-TetheringManager
    if ($null -eq $mgr) { return $false }
    if (-not (Test-MobileHotspotBandNeeds2Ghz $mgr)) { return $true }
    $restart = ($mgr.TetheringOperationalState.ToString() -eq 'On')
    return (Configure-MobileHotspotAccessPoint2Ghz $mgr $restart)
}

function Test-HotspotDhcpListening {
    return [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue)
}

function Get-EthernetUplinkAdapter {
    try {
        $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
            Sort-Object RouteMetric, InterfaceMetric
        foreach ($rt in @($routes)) {
            $if = Get-NetAdapter -InterfaceIndex $rt.InterfaceIndex -ErrorAction SilentlyContinue
            if ($null -eq $if -or $if.Status -ne 'Up') { continue }
            $d = ($if.Name + ' ' + $if.InterfaceDescription)
            if ($d -match 'Wireless|Wi-Fi|WiFi|WLAN|802\.11|WiFi Direct|Hosted') { continue }
            if ($d -match 'Virtual|Bluetooth|Direct|Hyper-V|VPN|Loopback') { continue }
            if ($d -match 'Ethernet|Gigabit|GbE|\bLAN\b') { return $if }
        }
    } catch {}
    return (Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
        $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'Ethernet|Gigabit|GbE' -and
        $_.InterfaceDescription -notmatch 'Virtual|Bluetooth|Wi-Fi|Wireless'
    } | Select-Object -First 1)
}

function Get-HotspotPrivateAdapter {
    foreach ($ip in @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' })) {
        $a = Get-NetAdapter -InterfaceIndex $ip.InterfaceIndex -ErrorAction SilentlyContinue
        if ($a -and ($a.InterfaceDescription -match 'Direct|Hosted' -or $a.Name -match 'Local Area Connection')) {
            return $a
        }
    }
    return (Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
        $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection\*')
    } | Select-Object -First 1)
}

function Test-EthernetHotspotIcsActive {
    param(
        [object]$EthernetAdapter,
        [object]$HotspotAdapter
    )
    if (-not $EthernetAdapter -or -not $HotspotAdapter) { return $false }
    $ethLive = Get-NetAdapter -InterfaceIndex $EthernetAdapter.ifIndex -ErrorAction SilentlyContinue
    $apLive = Get-NetAdapter -InterfaceIndex $HotspotAdapter.ifIndex -ErrorAction SilentlyContinue
    if (-not $ethLive -or -not $apLive) { return $false }
    function NormGuid($g) {
        if ($null -eq $g) { return '' }
        return ($g.ToString().Trim('{', '}').ToLowerInvariant())
    }
    $ethG = NormGuid($ethLive.InterfaceGuid)
    $apG = NormGuid($apLive.InterfaceGuid)
    $share = New-Object -ComObject HNetCfg.HNetShare
    $ethPublic = $false
    $apPrivate = $false
    foreach ($conn in @($share.EnumEveryConnection())) {
        try {
            $p = $share.NetConnectionProps($conn)
            $g = NormGuid $p.Guid
            $cfg = $share.INetSharingConfigurationForINetConnection($conn)
            if (-not $cfg.SharingEnabled) { continue }
            $st = [int]$cfg.SharingConnectionType
            if ($g -eq $ethG -and $st -eq 0) { $ethPublic = $true }
            if ($g -eq $apG -and $st -eq 1) { $apPrivate = $true }
        } catch {}
    }
    return ($ethPublic -and $apPrivate)
}

function Enable-EthernetHotspotIcs {
    <#
    Internet Connection Sharing: Ethernet (public/WAN) -> Mobile hotspot / Wi-Fi Direct (private/LAN).
    Required for PS5 when PC internet is on cable — Mobile Hotspot alone does not bridge Ethernet.

    Use -ManualIcsOnly when sharing was set in Control Panel — skips HNetCfg reset (avoids freezes).
    #>
    param([switch]$Quiet, [switch]$ManualIcsOnly)

    foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc', 'Dhcp')) {
        try { Start-Service $svc -ErrorAction SilentlyContinue } catch {}
    }

    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq '192.168.137.1' } |
        ForEach-Object {
            $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
            if ($a -and $a.InterfaceDescription -notmatch 'Direct|Hosted' -and $a.Name -notmatch 'Local Area Connection') {
                if (-not $Quiet) {
                    Write-Host "Removing stale 192.168.137.1 from $($a.Name)..."
                }
                Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -ErrorAction SilentlyContinue
            }
        }

    if (-not (Ensure-MobileHotspotOnRobust -Quiet)) {
        if (-not $Quiet) {
            Write-Host 'ERROR: Mobile Hotspot is not on (no 192.168.137.1). Turn it ON in Settings first.'
        }
        return $false
    }

    $eth = Get-EthernetUplinkAdapter
    $ap = Get-HotspotPrivateAdapter
    if (-not $eth) {
        if (-not $Quiet) { Write-Host 'ERROR: No Ethernet adapter found. Plug in the cable first.' }
        return $false
    }
    if (-not $ap) {
        if (-not $Quiet) {
            Write-Host 'ERROR: Hotspot virtual adapter not found. Toggle hotspot OFF 10s ON in Settings.'
        }
        return $false
    }

    if (-not $Quiet) {
        Write-Host "ICS pair: Ethernet [$($eth.Name)] (internet) -> [$($ap.Name)] (PS5 hotspot)"
    }

    if ((Test-HotspotDhcpListening) -and (Test-EthernetHotspotIcsActive $eth $ap)) {
        if (-not $Quiet) { Write-Host 'ICS already active (DHCP + sharing).' }
        return $true
    }
    if ($ManualIcsOnly -and (Test-HotspotDhcpListening) -and (Test-MobileHotspotGateway)) {
        if (-not $Quiet) {
            Write-Host 'DHCP + 192.168.137.1 OK — leaving ICS as set in Control Panel (no COM reset).'
        }
        return $true
    }

    function NormGuid($g) {
        if ($null -eq $g) { return '' }
        return ($g.ToString().Trim('{', '}').ToLowerInvariant())
    }
    function EnableShare($cfg, [int]$kind) {
        try { $cfg.EnableSharing([int32]$kind); return $true } catch { return $false }
    }

    $share = New-Object -ComObject HNetCfg.HNetShare
    $connMap = @{}
    foreach ($conn in @($share.EnumEveryConnection())) {
        try {
            $p = $share.NetConnectionProps($conn)
            $connMap[(NormGuid $p.Guid)] = @{
                cfg  = $share.INetSharingConfigurationForINetConnection($conn)
                name = $p.Name
            }
        } catch {}
    }
    $ethLive = Get-NetAdapter -InterfaceIndex $eth.ifIndex -ErrorAction SilentlyContinue
    $apLive = Get-NetAdapter -InterfaceIndex $ap.ifIndex -ErrorAction SilentlyContinue
    if (-not $ethLive -or -not $apLive) { return $false }
    $ethG = NormGuid($ethLive.InterfaceGuid)
    $apG = NormGuid($apLive.InterfaceGuid)
    $ethK = $null
    $apK = $null
    foreach ($k in $connMap.Keys) {
        if ($k -eq $ethG) { $ethK = $k }
        if ($k -eq $apG) { $apK = $k }
    }
    if (-not $ethK) {
        $w = $eth.Name.ToLowerInvariant()
        foreach ($k in $connMap.Keys) {
            if (($connMap[$k].name -as [string]).ToLowerInvariant() -eq $w) { $ethK = $k }
        }
    }
    if (-not $apK) {
        $w = $ap.Name.ToLowerInvariant()
        foreach ($k in $connMap.Keys) {
            if (($connMap[$k].name -as [string]).ToLowerInvariant() -eq $w) { $apK = $k }
        }
    }
    if (-not $ethK -or -not $apK) {
        if (-not $Quiet) { Write-Host "ERROR: Could not map adapters for ICS (eth=$ethK ap=$apK)." }
        return $false
    }

    # Only reset sharing on the Ethernet + hotspot pair (mass DisableSharing freezes ncpa.cpl).
    foreach ($k in @($ethK, $apK)) {
        try {
            if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing() }
        } catch {}
    }
    Start-Sleep -Seconds 1

    if (-not $Quiet) { Write-Host 'Enabling Internet Connection Sharing...' }
    $ok = (EnableShare $connMap[$ethK].cfg 0) -and (EnableShare $connMap[$apK].cfg 1)
    if (-not $ok) {
        foreach ($k in $connMap.Keys) {
            try { if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing() } } catch {}
        }
        Start-Sleep -Milliseconds 500
        $ok = (EnableShare $connMap[$apK].cfg 1) -and (EnableShare $connMap[$ethK].cfg 0)
    }

    Restart-Service SharedAccess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 6

    $dhcp = Test-HotspotDhcpListening
    $ics = Test-EthernetHotspotIcsActive $eth $ap
    if (-not $Quiet) {
        Write-Host "DHCP (port 67): $dhcp | ICS sharing: $ics"
    }
    return ($dhcp -and $ics)
}

function Show-EthernetHotspotIcsManualSteps {
    $ap = Get-HotspotPrivateAdapter
    $apName = if ($ap) { $ap.Name } else { 'Local Area Connection* (Wi-Fi Direct)' }
    Write-Host ''
    Write-Host 'Manual sharing (one-time on Realtek USB) — use ETHERNET, not Wi-Fi:'
    Write-Host '  1. Win+R -> ncpa.cpl -> Enter'
    Write-Host '  2. Right-click your Ethernet adapter -> Properties -> Sharing tab'
    Write-Host '  3. Check "Allow other network users to connect through this computer''s Internet connection"'
    Write-Host "  4. Home networking connection: $apName"
    Write-Host '  5. OK -> toggle Mobile hotspot OFF 15 sec ON -> reconnect PS5 to osps'
    Write-Host ''
    try { Start-Process 'ncpa.cpl' } catch {}
}

function Test-EthernetInternetUplink {
    try {
        $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
            Sort-Object RouteMetric, InterfaceMetric
        foreach ($rt in @($routes)) {
            $if = Get-NetAdapter -InterfaceIndex $rt.InterfaceIndex -ErrorAction SilentlyContinue
            if ($null -eq $if -or $if.Status -ne 'Up') { continue }
            $d = ($if.Name + ' ' + $if.InterfaceDescription)
            if ($d -match 'Wireless|Wi-Fi|WiFi|WLAN|802\.11|WiFi Direct|Hosted') { continue }
            if ($d -match 'Virtual|Bluetooth|Direct|Hyper-V|VPN|Loopback') { continue }
            if ($d -match 'Ethernet|Gigabit|GbE|\bLAN\b') {
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

function Get-WifiUplinkSsid {
    $ifaces = netsh wlan show interfaces 2>$null | Out-String
    if ($ifaces -match 'SSID\s*:\s*(.+)\r?\n') { return $Matches[1].Trim() }
    $prof = netsh wlan show profiles 2>$null | Out-String
    if ($prof -match 'All User Profile\s*:\s*(.+)\r?\n') { return $Matches[1].Trim() }
    return $null
}

function Connect-WifiToBssid {
    param(
        [Parameter(Mandatory)][string]$Ssid,
        [Parameter(Mandatory)][string]$Bssid,
        [string]$Iface = (Get-WifiClientInterfaceName)
    )
    netsh wlan connect name="$Ssid" ssid="$Ssid" interface="$Iface" bss="$Bssid" 2>$null | Out-Null
}

function Reconnect-WifiProfile {
    param(
        [Parameter(Mandatory)][string]$Ssid,
        [string]$Iface = (Get-WifiClientInterfaceName)
    )
    netsh wlan connect name="$Ssid" interface="$Iface" 2>$null | Out-Null
}

function Connect-WifiUplinkToBand {
    <#
    Switch uplink to a band without leaving Wi-Fi offline: try BSSID connect first,
    disconnect only if needed, then fall back to a normal profile reconnect.
    #>
    param(
        [ValidateSet('2.4', '5')]
        [string]$Band,
        [switch]$StopHotspotFirst
    )
    if ($StopHotspotFirst) {
        Stop-MobileHotspotIfOn | Out-Null
        Start-Sleep -Seconds 2
    }
    $ssid = Get-WifiUplinkSsid
    if (-not $ssid) { return $false }

    $want5 = ($Band -eq '5')
    $ch = Get-WifiUplinkChannel
    if ($want5 -and $ch -gt 14) { return $true }
    if (-not $want5 -and $ch -ge 1 -and $ch -le 14) { return $true }

    $target = Find-BssidForSsidBand -Ssid $ssid -Band $Band
    if (-not $target) { return $false }

    $iface = Get-WifiClientInterfaceName
    $ok = {
        $c = Get-WifiUplinkChannel
        if ($want5) { return ($c -gt 14) }
        return ($c -ge 1 -and $c -le 14)
    }

    Connect-WifiToBssid -Ssid $target.Ssid -Bssid $target.Bssid -Iface $iface
    Start-Sleep -Seconds 8
    if (& $ok) { return $true }

    netsh wlan disconnect interface="$iface" 2>$null | Out-Null
    Start-Sleep -Seconds 2
    Connect-WifiToBssid -Ssid $target.Ssid -Bssid $target.Bssid -Iface $iface
    Start-Sleep -Seconds 10
    if (& $ok) { return $true }

    # Last resort: get back online on the saved profile (avoid leaving Wi-Fi off).
    Reconnect-WifiProfile -Ssid $ssid -Iface $iface
    Start-Sleep -Seconds 8
    return (& $ok)
}

function Connect-WifiUplinkTo5Ghz {
    # Hotspot must be off on single-radio USB before the client can rejoin 5 GHz.
    return (Connect-WifiUplinkToBand -Band '5' -StopHotspotFirst)
}

function Test-MobileHotspotGateway {
    return [bool](Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1)
}

function Set-HotspotDhcpRegistry {
    $saParams = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
    foreach ($name in @('ScopeAddress', 'ScopeAddressBackup', 'StandaloneDhcpAddress')) {
        try {
            Set-ItemProperty -Path $saParams -Name $name -Value '192.168.137.1' -Type String -Force -ErrorAction SilentlyContinue
        } catch {}
    }
}

function Ensure-HotspotDhcpFirewall {
    foreach ($r in @(
        @{ N = 'ZubCut-DHCP-In'; D = 'in'; LP = '67' },
        @{ N = 'ZubCut-DHCP-Out'; D = 'out'; LP = '67' },
        @{ N = 'ZubCut-DHCP-Bcast-In'; D = 'in'; LP = '67'; RIP = '255.255.255.255/32' },
        @{ N = 'ZubCut-DHCP-Subnet-In'; D = 'in'; LP = '67'; RIP = '192.168.137.0/24' },
        @{ N = 'ZubCut-DHCP-Subnet-Out'; D = 'out'; LP = '67,68'; RIP = '192.168.137.0/24' },
        @{ N = 'ZubCut-DHCP-Client-In'; D = 'in'; LP = '68'; RIP = '192.168.137.0/24' }
    )) {
        netsh advfirewall firewall delete rule name="$($r.N)" 2>$null | Out-Null
        $args = @(
            'advfirewall', 'firewall', 'add', 'rule',
            "name=$($r.N)", "dir=$($r.D)", 'action=allow', 'protocol=UDP', 'enable=yes'
        )
        if ($r.LP) { $args += "localport=$($r.LP)" }
        if ($r.RIP) { $args += "remoteip=$($r.RIP)" }
        & netsh @args 2>$null | Out-Null
    }
}

function Ensure-MobileHotspotOnRobust {
    param([switch]$Quiet)
    foreach ($svc in @('SharedAccess', 'icssvc', 'WlanSvc', 'Dhcp')) {
        try { Start-Service $svc -ErrorAction SilentlyContinue } catch {}
    }
    Set-HotspotDhcpRegistry
    Ensure-HotspotDhcpFirewall

    if (Test-MobileHotspotGateway) { return $true }

    $mgr = Get-TetheringManager
    if ($null -ne $mgr -and $mgr.TetheringOperationalState.ToString() -ne 'On') {
        if (-not $Quiet) { Write-Host 'Starting Mobile Hotspot via Windows API...' }
        $op = $mgr.StartTetheringAsync()
        if (Wait-WinRtAsync $op 'StartTethering' 45) {
            Start-Sleep -Seconds 8
        }
    }
    if (Test-MobileHotspotGateway) { return $true }

    if (-not $Quiet) {
        Write-Host ''
        Write-Host 'Hotspot is not running yet (no 192.168.137.1).'
        Write-Host 'Opening Settings -> turn Mobile hotspot ON, wait 10 seconds.'
        Write-Host 'This window will wait up to 90 seconds...'
        try { Start-Process 'ms-settings:network-mobilehotspot' } catch {}
    }
    for ($i = 0; $i -lt 45; $i++) {
        if (Test-MobileHotspotGateway) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Test-Ps5HotspotReady {
    $eth = Get-EthernetUplinkAdapter
    $ap = Get-HotspotPrivateAdapter
    $dhcp = Test-HotspotDhcpListening
    $ics = $false
    if ($eth -and $ap) {
        $ics = Test-EthernetHotspotIcsActive -EthernetAdapter $eth -HotspotAdapter $ap
    }
    [PSCustomObject]@{
        Gateway        = (Test-MobileHotspotGateway)
        HotspotAdapter = if ($ap) { $ap.Name } else { '(not up — turn hotspot ON)' }
        Ethernet       = if ($eth) { $eth.Name } else { '(no cable)' }
        Dhcp           = $dhcp
        IcsSharing     = $ics
        Ready          = ((Test-MobileHotspotGateway) -and $dhcp -and $ics)
    }
}

function Show-Ps5HotspotStatus {
    $s = Test-Ps5HotspotReady
    Write-Host "  Hotspot gateway (192.168.137.1): $($s.Gateway)"
    Write-Host "  Hotspot adapter: $($s.HotspotAdapter)"
    Write-Host "  Ethernet uplink: $($s.Ethernet)"
    Write-Host "  DHCP for PS5 (port 67): $($s.Dhcp)"
    Write-Host "  Internet sharing (ICS): $($s.IcsSharing)"
    Write-Host "  PS5 can connect: $($s.Ready)"
    return $s
}

function Repair-Ps5HotspotEthernet {
    <#
    Full repair: Ethernet internet + 2.4 GHz hotspot + ICS + DHCP.
    Use when PS5 cannot connect or Fix Hotspot Sharing failed.
    #>
    if (-not (Test-EthernetInternetUplink)) {
        Write-Host 'ERROR: Plug Ethernet from PC to router first (Settings -> Ethernet = Connected).'
        return $false
    }
    Write-Host '=== Repair PS5 hotspot (Ethernet -> hotspot) ==='
    Disconnect-WifiClientForEthernetHotspot | Out-Null
    Ensure-EthernetPreferredRouting | Out-Null

    Write-Host ''
    Write-Host 'Step 1: Mobile Hotspot must be ON...'
    if (-not (Ensure-MobileHotspotOnRobust)) {
        Write-Host 'FAILED: Hotspot never came up. In Settings, turn Mobile hotspot ON manually, then run this again.'
        return $false
    }

    Write-Host ''
    Write-Host 'Step 2: 2.4 GHz hotspot band...'
    Set-MobileHotspotBandRegistry2Ghz | Out-Null
    $mgrBand = Get-TetheringManager
    if ($mgrBand) {
        Configure-MobileHotspotAccessPoint2Ghz $mgrBand $false | Out-Null
    }

    Write-Host ''
    Write-Host 'Step 3: Internet Connection Sharing (Ethernet -> hotspot)...'
    if (-not (Enable-EthernetHotspotIcs)) {
        Write-Host 'Automatic sharing failed.'
        Show-EthernetHotspotIcsManualSteps
        Write-Host ''
        Write-Host 'After manual sharing: toggle hotspot OFF 15 sec ON, then run this script again.'
        return $false
    }

    Write-Host ''
    Write-Host '=== Status ==='
    $s = Show-Ps5HotspotStatus
    if ($s.Ready) {
        Write-Host ''
        Write-Host 'SUCCESS: Connect PS5 to osps (password in Settings -> Mobile hotspot).'
        Write-Host 'Use 2.4 GHz only — PS5 often cannot use 5 GHz PC hotspots.'
        return $true
    }
    Write-Host ''
    Write-Host 'Still not ready — toggle hotspot OFF 15 sec ON, reconnect PS5.'
    return $false
}

function Start-MobileHotspotAfter2GhzConfig {
    if (Ensure-MobileHotspotOnRobust -Quiet) { return $true }
    $mgr = Get-TetheringManager
    if ($null -eq $mgr) { return $false }
    if ($mgr.TetheringOperationalState.ToString() -eq 'On') { return $true }
    $op = $mgr.StartTetheringAsync()
    if (-not (Wait-WinRtAsync $op 'StartTethering' 40)) { return $false }
    Start-Sleep -Seconds 5
    return (Test-MobileHotspotGateway)
}
