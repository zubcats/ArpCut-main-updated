# ZubCut Quick Network Diagnostic (no Python / no repo required)
# Right-click -> Run with PowerShell  (or run elevated for best results)
# Writes ZubCut-Quick-Diag-*.txt under Desktop\ZubCut Diagnostics.
# SUMMARY uses x-masked IPs so screenshots stay privacy-safe.

$ErrorActionPreference = 'SilentlyContinue'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$desktop = [Environment]::GetFolderPath('Desktop')
$diagDir = Join-Path $desktop 'ZubCut Diagnostics'
if (-not (Test-Path -LiteralPath $diagDir)) {
    New-Item -ItemType Directory -Path $diagDir -Force | Out-Null
}
$out = Join-Path $diagDir "ZubCut-Quick-Diag-$stamp.txt"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Has-UninstallDisplay([string]$needle) {
    $paths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    Get-ItemProperty $paths -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -and ($_.DisplayName -match $needle) } |
        Select-Object -ExpandProperty DisplayName -Unique
}

function Format-SafeIPv4([string]$ip) {
    # Mask with x — keep host cues; same-subnet is reported separately as PASS/FAIL.
    if (-not $ip) { return '(ip)' }
    $ip = $ip.Trim()
    if ($ip -match '^(192)\.(168)\.(137)\.(\d+)$') {
        return '192.168.137.x'
    }
    if ($ip -match '^(169)\.(254)\.(\d+)\.(\d+)$') {
        return '169.254.x.x'
    }
    if ($ip -match '^(127)\.(\d+)\.(\d+)\.(\d+)$') {
        return ("127.x.x.{0}" -f $Matches[4])
    }
    if ($ip -match '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') {
        $a = [int]$Matches[1]; $b = [int]$Matches[2]; $c = [int]$Matches[3]; $d = [int]$Matches[4]
        if (($a -eq 192) -and ($b -eq 168)) {
            return ("192.168.x.{0}" -f $d)
        }
        if ($a -eq 10) {
            return ("10.x.x.{0}" -f $d)
        }
        if (($a -eq 172) -and ($b -ge 16) -and ($b -le 31)) {
            return ("172.x.x.{0}" -f $d)
        }
        if (($a -eq 100) -and ($b -ge 64) -and ($b -le 127)) {
            return ("100.x.x.{0}" -f $d)
        }
        return ("x.x.x.{0}" -f $d)
    }
    return '(ip)'
}

function Test-SameSubnet([string]$ipA, [string]$ipB, [int]$prefixLen = 24) {
    if ($ipA -notmatch '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') { return $false }
    $a = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], [int]$Matches[4])
    if ($ipB -notmatch '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') { return $false }
    $b = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], [int]$Matches[4])
    if ($prefixLen -lt 0 -or $prefixLen -gt 32) { $prefixLen = 24 }
    if ($prefixLen -eq 24) {
        return ($a[0] -eq $b[0] -and $a[1] -eq $b[1] -and $a[2] -eq $b[2])
    }
    if ($prefixLen -eq 0) { return $true }
    $ai = [int64](($a[0] -shl 24) -bor ($a[1] -shl 16) -bor ($a[2] -shl 8) -bor $a[3])
    $bi = [int64](($b[0] -shl 24) -bor ($b[1] -shl 16) -bor ($b[2] -shl 8) -bor $b[3])
    $mask = [int64](([int64]0xFFFFFFFF -shl (32 - $prefixLen)) -band [int64]0xFFFFFFFF)
    return (($ai -band $mask) -eq ($bi -band $mask))
}
function Test-SameSlash24([string]$ipA, [string]$ipB) { return Test-SameSubnet $ipA $ipB 24 }

function Test-MobileHotspotOn {
    # Match Windows Settings → Mobile Hotspot toggle (not leftover 192.168.137.x).
    try {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction SilentlyContinue
        [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
        [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
        $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
        if (-not $profile) { return $false }
        $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
        return ($mgr.TetheringOperationalState.ToString() -eq 'On')
    } catch {
        return $false
    }
}

function Get-BandFromChannel([int]$ch) {
    if ($ch -le 0) { return $null }
    if ($ch -le 14) { return '2.4 GHz' }
    if ($ch -gt 177) { return '6 GHz' }
    return '5 GHz'
}

function Get-SecurityZubCutClass([string]$auth) {
    $a = ($auth | Out-String).Trim().ToLowerInvariant()
    if (-not $a) { return 'unknown' }
    if ($a -match 'wpa3' -or $a -match 'sae') { return 'wpa3' }
    if ($a -match 'wpa2') { return 'wpa2' }
    if ($a -eq 'open' -or $a -eq 'none' -or $a -match 'wep') { return 'weak' }
    if ($a -match '\bwpa\b') { return 'weak' }
    return 'unknown'
}

$admin = Test-IsAdmin
$npcapCandidates = @(
    'C:\Windows\System32\npcap',
    'C:\Windows\SysWOW64\npcap'
)
$npcapPath = $null
foreach ($cand in $npcapCandidates) {
    if (Test-Path $cand) { $npcapPath = $cand; break }
}
if (-not $npcapPath) { $npcapPath = $npcapCandidates[0] }
$npcapOk = Test-Path $npcapPath
$npcapSvc = Get-Service -Name 'npcap', 'npf' -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq 'Running' } |
    Select-Object -First 1
$npcapSvcOk = $null -ne $npcapSvc
$npcapSvcName = if ($npcapSvc) { $npcapSvc.Name } else { '(none running)' }
$npcapAdminOnly = $false
$npcapWinPcapCompat = $true
try {
    $npcapParams = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\npcap\Parameters' -ErrorAction SilentlyContinue
    if ($npcapParams) {
        if ($null -ne $npcapParams.AdminOnly) { $npcapAdminOnly = ([int]$npcapParams.AdminOnly -ne 0) }
        if ($null -ne $npcapParams.WinPcapCompatible) { $npcapWinPcapCompat = ([int]$npcapParams.WinPcapCompatible -ne 0) }
    }
} catch {}

$winpcapKey = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst'
if (-not $winpcapKey) {
    $winpcapKey = Test-Path 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst'
}
$winpcapApps = @(Has-UninstallDisplay 'WinPcap|Win10Pcap')
$npcapApps = @(Has-UninstallDisplay 'Npcap')
$nmapApps = @(Has-UninstallDisplay 'Nmap')

# IP forwarding — ON causes Kill to feel like lag without full offline.
$ipFwd = 0
try {
    $ipFwd = [int](Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' `
        -Name 'IPEnableRouter' -ErrorAction SilentlyContinue).IPEnableRouter
} catch { $ipFwd = 0 }
$ipFwdOn = $ipFwd -ne 0

$zubcutDirs = @(
    (Join-Path $env:ProgramFiles 'ZubCut'),
    (Join-Path ${env:ProgramFiles(x86)} 'ZubCut'),
    (Join-Path $env:LOCALAPPDATA 'ZubCut')
) | Where-Object { $_ -and (Test-Path $_) }

$wdBundles = @()
foreach ($d in $zubcutDirs) {
    $wd = Join-Path $d 'windivert'
    $dll = Test-Path (Join-Path $wd 'WinDivert.dll')
    $sys = Test-Path (Join-Path $wd 'WinDivert64.sys')
    $wdBundles += [pscustomobject]@{ Dir = $wd; Dll = $dll; Sys = $sys; Complete = ($dll -and $sys) }
}
$wdOk = ($wdBundles | Where-Object Complete).Count -gt 0

$ipcfg = ipconfig | Out-String
# Mobile Hotspot ON/OFF from Windows tethering API — do not treat any leftover
# 192.168.137.x (ICS / SoftAP) as "hotspot on" when the Settings toggle is off.
$hotspotOn = Test-MobileHotspotOn
# Full ICS uses 192.168.137.1; Hosted Network standalone DHCP uses 192.168.173.1.
$icsGw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -in @('192.168.137.1', '192.168.173.1') } |
    Select-Object -First 1
$hasIcsGw = $null -ne $icsGw
$hotspotReady = $hotspotOn -and $hasIcsGw
$dhcp67 = $false
try { $dhcp67 = [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue) } catch { $dhcp67 = $false }
$clients137 = @(
    Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            (
                ($_.IPAddress -like '192.168.137.*' -and $_.IPAddress -ne '192.168.137.1') -or
                ($_.IPAddress -like '192.168.173.*' -and $_.IPAddress -ne '192.168.173.1')
            ) -and
            $_.State -in @('Reachable', 'Stale', 'Permanent', 'Probe', 'Delay')
        }
)
$clientCount = $clients137.Count
$gateways = [regex]::Matches(
    $ipcfg,
    '(?i)(?:Default Gateway|Passerelle par d[eé]faut|Standardgateway|Puerta de enlace predeterminada|Gateway predefinito)[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})'
) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
if (-not $gateways) {
    $gateways = [regex]::Matches(
        $ipcfg,
        '(?i)(?:gateway|passerelle|gateway)[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})'
    ) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
}
try {
    $routeGws = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Where-Object { $_.NextHop -and $_.NextHop -ne '0.0.0.0' } |
        Select-Object -ExpandProperty NextHop -Unique
    if ($routeGws) { $gateways = @($routeGws | Sort-Object -Unique) }
} catch {}

$adapters = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' } |
    Select-Object InterfaceAlias, IPAddress, PrefixOrigin

$settingsPath = Join-Path $env:APPDATA 'ZubCut\zubcut.json'
$clumsy = $null
$ifaceSaved = $null
if (Test-Path $settingsPath) {
    try {
        $js = Get-Content $settingsPath -Raw | ConvertFrom-Json
        if ($js -is [System.Array]) {
            # legacy array form — skip structured fields
        } else {
            $clumsy = $js.clumsy_mode
            $ifaceSaved = $js.iface
        }
    } catch {}
}

# Saved Settings adapter live? (exists, IPv4, not APIPA)
$savedLive = $false
$savedApipa = $false
$savedIp = $null
if ($ifaceSaved) {
    $savedAddrs = @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.InterfaceAlias -eq $ifaceSaved -and $_.IPAddress -notlike '127.*' }
    )
    if ($savedAddrs.Count -eq 0 -and $ifaceSaved -match '^\{?[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\}?$') {
        $guidNorm = $ifaceSaved.Trim('{}').ToUpperInvariant()
        $adp = Get-NetAdapter -ErrorAction SilentlyContinue |
            Where-Object { $_.InterfaceGuid.ToString().Trim('{}').ToUpperInvariant() -eq $guidNorm } |
            Select-Object -First 1
        if ($adp) {
            $savedAddrs = @(
                Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $adp.ifIndex -ErrorAction SilentlyContinue |
                    Where-Object { $_.IPAddress -notlike '127.*' }
            )
        }
    }
    if ($savedAddrs.Count -gt 0) {
        $savedIp = [string]$savedAddrs[0].IPAddress
        $savedApipa = $savedIp -like '169.254.*'
        $savedLive = -not $savedApipa
    }
}

# Gateway MAC from ARP (needed for MITM)
$gwPrimary = if ($gateways) { [string]$gateways[0] } else { $null }
$gwMac = $null
$gwMacOk = $false
if ($gwPrimary) {
    $arpAll = arp -a | Out-String
    $macRx = [regex]::Match(
        $arpAll,
        [regex]::Escape($gwPrimary) + '\s+([0-9a-fA-F\-]{17})'
    )
    if ($macRx.Success) {
        $gwMac = $macRx.Groups[1].Value
        $gwMacOk = $gwMac -and ($gwMac -notmatch '^(ff-ff-ff-ff-ff-ff|00-00-00-00-00-00)$')
    }
}

# PC vs gateway same subnet (prefix from adapter; default /24)
$pcIp = $null
foreach ($a in $adapters) {
    if ($a.IPAddress -and ($a.IPAddress -notlike '169.254.*') -and ($a.IPAddress -notlike '192.168.137.*') -and ($a.IPAddress -notlike '192.168.173.*')) {
        $pcIp = [string]$a.IPAddress
        break
    }
}
if (-not $pcIp -and $savedIp) { $pcIp = $savedIp }
$pcGwSame = $false
$pcPrefix = 24
try {
    if ($pcIp) {
        $pcAddr = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $pcIp -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($pcAddr -and $pcAddr.PrefixLength) { $pcPrefix = [int]$pcAddr.PrefixLength }
    }
} catch { $pcPrefix = 24 }
if ($pcIp -and $gwPrimary) {
    $pcGwSame = Test-SameSubnet $pcIp $gwPrimary $pcPrefix
}

$lines = @()
$lines += '========================================================================'
$lines += ' ZubCut Quick Check (all-in-one)'
$lines += '========================================================================'
$lines += ("Generated: {0}" -f (Get-Date).ToString('u'))
$lines += ("Administrator: {0}" -f $(if ($admin) { 'yes' } else { 'NO — approve UAC / Run as administrator' }))
$lines += 'IPs in SUMMARY are masked with x for screenshot privacy.'
$lines += 'Includes: path, Npcap/capture, Wi-Fi link, LAN Kill, Clumsy hotspot.'
$lines += ''
$lines += '>>> SCREENSHOT THIS SUMMARY <<<'
$lines += '------------------------------------------------------------------------'
# Which setup this report is for (Settings + hotspot) — not advice to change modes.
if ($clumsy) {
    if ($hotspotReady) {
        $lines += '[INFO] Active path: Clumsy hotspot (Clumsy ON, Mobile Hotspot ready)'
    } else {
        $lines += '[INFO] Active path: Clumsy hotspot (Clumsy ON — hotspot not ready yet)'
    }
} else {
    $lines += '[INFO] Active path: LAN Kill (Clumsy OFF)'
}
$lines += ("[{0}] Running as Administrator" -f $(if ($admin) { 'PASS' } else { 'FAIL' }))

# --- Capture stack (written by ZubCut before launch, when available) ---
$lines += '--- Capture stack ---'
$capSnippet = Join-Path $env:TEMP 'ZubCut\quick-capture-snippet.txt'
if (Test-Path -LiteralPath $capSnippet) {
    Get-Content -LiteralPath $capSnippet -ErrorAction SilentlyContinue | ForEach-Object { $lines += $_ }
} else {
    $lines += '[WARN] Capture stack not probed — open Quick check from ZubCut as Admin'
}

$lines += '--- Environment ---'
$lines += ("[{0}] Npcap folder present ({1})" -f $(if ($npcapOk) { 'PASS' } else { 'FAIL' }), $npcapPath)
$lines += ("[{0}] Npcap/NPF service running ({1})" -f $(if ($npcapSvcOk) { 'PASS' } else { 'FAIL' }), $npcapSvcName)
$lines += ("[{0}] Npcap AdminOnly off (or ZubCut elevated)" -f $(if ($npcapAdminOnly -and -not $admin) { 'FAIL' } else { 'PASS' }))
$lines += ("[{0}] Npcap WinPcap-compatible mode (or System32/npcap DLLs)" -f $(if ($npcapWinPcapCompat -or $npcapOk) { 'PASS' } else { 'WARN' }))
$lines += ("[{0}] WinPcap uninstall key absent" -f $(if ($winpcapKey) { 'FAIL' } else { 'PASS' }))
$lines += ("[{0}] WinPcap/Win10Pcap not in Apps list" -f $(if ($winpcapApps.Count) { 'FAIL' } else { 'PASS' }))
$lines += ("[{0}] IP forwarding off (Kill full-cut)" -f $(if ($ipFwdOn) { 'FAIL' } else { 'PASS' }))
$lines += ("[{0}] WinDivert bundle under ZubCut" -f $(if ($wdOk) { 'PASS' } else { 'WARN' }))

$lines += '--- LAN path ---'
$lines += ("[{0}] Gateway MAC known (MITM)" -f $(if ($gwMacOk) { 'PASS' } else { 'FAIL' }))
if ($ifaceSaved) {
    if ($savedLive) {
        $lines += ("[PASS] Settings adapter live: {0} ({1})" -f $ifaceSaved, (Format-SafeIPv4 $savedIp))
    } elseif ($savedApipa) {
        $lines += ("[FAIL] Settings adapter APIPA only: {0} ({1})" -f $ifaceSaved, (Format-SafeIPv4 $savedIp))
    } else {
        $lines += ("[FAIL] Settings adapter not live / no IPv4: {0}" -f $ifaceSaved)
    }
} else {
    $lines += '[WARN] Settings adapter not set'
}
if ($pcIp -and $gwPrimary) {
    $lines += ("[{0}] PC and gateway on same subnet (/{1})" -f $(if ($pcGwSame) { 'PASS' } else { 'FAIL' }), $pcPrefix)
    $lines += ("[INFO] PC {0}  GW {1}" -f (Format-SafeIPv4 $pcIp), (Format-SafeIPv4 $gwPrimary))
} else {
    $lines += '[WARN] Could not compare PC IP vs gateway subnet'
}
if ($gwMacOk) { $lines += ("[INFO] Gateway MAC: {0}" -f $gwMac) }
$gwSafe = @($gateways | ForEach-Object { Format-SafeIPv4 $_ })
$lines += ("[INFO] Default gateways: {0}" -f ($(if ($gwSafe) { $gwSafe -join ', ' } else { '(none)' })))
$lines += ("[INFO] Saved adapter (settings): {0}" -f ($(if ($ifaceSaved) { $ifaceSaved } else { '(not set)' })))
$lines += ("[INFO] Clumsy mode (settings): {0}" -f ($(if ($null -eq $clumsy) { '(unknown)' } else { $clumsy })))

$lines += '--- Hotspot path ---'
if ($hotspotOn) {
    if ($hasIcsGw) {
        $gwShown = if ($icsGw) { [string]$icsGw.IPAddress } else { '192.168.137.1' }
        $lines += ("[PASS] Mobile Hotspot ON (ICS/hosted GW {0})" -f $gwShown)
    } else {
        $lines += '[WARN] Mobile Hotspot ON but no 192.168.137.1 / 192.168.173.1 — wait or toggle hotspot'
    }
} elseif ($clumsy) {
    $lines += '[WARN] Mobile Hotspot OFF (Clumsy ON — turn Mobile Hotspot on in Settings)'
} else {
    $lines += '[INFO] Mobile Hotspot OFF (OK when Clumsy is off)'
}
if ($dhcp67) {
    $lines += '[PASS] Hotspot DHCP listening (UDP 67)'
} elseif ($clumsy -and $hotspotOn) {
    $lines += '[WARN] Hotspot DHCP not listening (UDP 67)'
} else {
    $lines += '[INFO] Hotspot DHCP (UDP 67) not listening'
}
if ($clientCount -gt 0) {
    $lines += ("[PASS] Hotspot client(s) seen on 192.168.137.x / 173.x: {0}" -f $clientCount)
} elseif ($clumsy -and $hotspotOn) {
    $lines += '[WARN] No hotspot client seen — put PS5 on this PC hotspot Wi-Fi, wait, rescan'
} else {
    $lines += '[INFO] No hotspot client on 192.168.137.x / 173.x'
}

# --- Wi-Fi link (this PC only) ---
$lines += '--- Wi-Fi link (this PC only) ---'
$wlanRaw = netsh wlan show interfaces | Out-String
function Fold-Latin([string]$s) {
    if (-not $s) { return '' }
    $n = $s.Normalize([Text.NormalizationForm]::FormD)
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $n.ToCharArray()) {
        if ([Globalization.CharUnicodeInfo]::GetUnicodeCategory($ch) -ne 'NonSpacingMark') {
            [void]$sb.Append($ch)
        }
    }
    return $sb.ToString().ToLowerInvariant()
}
function Canon-WlanKey([string]$k) {
    $f = Fold-Latin (($k -replace '\s+', ' ').Trim())
    switch -Regex ($f) {
        '^(name|nom|nombre|nome)$' { return 'Name' }
        '^(state|zustand|etat|estado|stato)$' { return 'State' }
        '^(ssid)$' { return 'SSID' }
        '^(band|bande|banda)$' { return 'Band' }
        '^(channel|kanal|canal|canale)$' { return 'Channel' }
        '^(authentication|authentifizierung|authentification|autenticacion|autenticazione)$' { return 'Authentication' }
        default { return (($k -replace '\s+', ' ').Trim()) }
    }
}
function Test-WlanConnected($st, $ssid) {
    $f = Fold-Latin ([string]$st)
    if ($f -in @('connected','verbunden','connecte','conectado','connesso')) { return $true }
    if ($f -in @('disconnected','getrennt','deconnecte','desconectado','disconnesso')) { return $false }
    return ([string]$ssid).Trim().Length -gt 0
}
$wlanAdapters = @()
$wlanCurrent = @{}
foreach ($line in ($wlanRaw -split "`r?`n")) {
    if ($line -match '^\s*(Name|Nom|Nombre|Nome)\s*:\s*(.+)\s*$') {
        if ($wlanCurrent.Count -gt 0 -and $wlanCurrent.ContainsKey('Name')) {
            $wlanAdapters += ,([pscustomobject]$wlanCurrent)
        }
        $wlanCurrent = @{ Name = $Matches[2].Trim() }
        continue
    }
    if ($line -match '^\s+(\S.*?)\s*:\s*(.*?)\s*$') {
        $key = Canon-WlanKey $Matches[1]
        $val = $Matches[2].Trim()
        if ($key) { $wlanCurrent[$key] = $val }
    }
}
if ($wlanCurrent.Count -gt 0 -and $wlanCurrent.ContainsKey('Name')) {
    $wlanAdapters += ,([pscustomobject]$wlanCurrent)
}
$wlanConnected = @($wlanAdapters | Where-Object {
        Test-WlanConnected $_.State $_.SSID
    })
if ($wlanAdapters.Count -eq 0) {
    $lines += '[FAIL] No Wi-Fi interface info (netsh wlan returned nothing)'
} elseif ($wlanConnected.Count -eq 0) {
    $lines += '[WARN] No connected Wi-Fi link'
} else {
    foreach ($a in $wlanConnected) {
        $ch = 0
        if ([string]$a.Channel -match '(\d+)') { $ch = [int]$Matches[1] }
        $band = [string]$a.Band
        if (-not $band) { $band = Get-BandFromChannel $ch }
        if (-not $band) { $band = '(unknown)' }
        $auth = if ($a.Authentication) { [string]$a.Authentication } else { '(unknown)' }
        $cipher = if ($a.Cipher) { [string]$a.Cipher } else { '(unknown)' }
        $radio = if ($a.'Radio type') { [string]$a.'Radio type' } else { '(unknown)' }
        $sig = if ($a.Signal) { [string]$a.Signal } else { '?' }
        $rx = if ($a.'Receive rate (Mbps)') { [string]$a.'Receive rate (Mbps)' } else { '?' }
        $tx = if ($a.'Transmit rate (Mbps)') { [string]$a.'Transmit rate (Mbps)' } else { '?' }
        $ssid = [string]$a.SSID
        $secCls = Get-SecurityZubCutClass $auth
        $lines += ('[PASS] Connected: {0}' -f $a.Name)
        $lines += ('[INFO] SSID: {0}' -f $ssid)
        $lines += ('[INFO] Band: {0} (channel {1})' -f $band, $(if ($ch -gt 0) { $ch } else { '?' }))
        $lines += ('[INFO] Security: {0} / {1}' -f $auth, $cipher)
        if ($secCls -eq 'wpa2') {
            $lines += '[PASS] WPA2 — OK for ZubCut'
        } elseif ($secCls -eq 'wpa3') {
            $lines += '[WARN] WPA3 — ZubCut Kill/MITM usually fails; set Wi-Fi to WPA2-Personal'
        } elseif ($secCls -eq 'weak') {
            $lines += '[WARN] Weak/open Wi-Fi security — use WPA2-Personal for ZubCut'
        }
        $lines += ('[INFO] Radio: {0}  Signal: {1}' -f $radio, $sig)
        $lines += ('[INFO] Rates: rx {0} Mbps / tx {1} Mbps' -f $rx, $tx)
        if ($radio -match '802\.11be|Wi-?Fi\s*7|\bbe\b') {
            $lines += '[WARN] Wi-Fi 7 / 802.11be — MLO can drop ARP between clients (ZC-MLO); disable MLO or use Mobile Hotspot / Ethernet'
        }
        if ($a.GUID) { $lines += ('[INFO] Adapter GUID: {0}' -f $a.GUID) }
        if ($a.BSSID) { $lines += ('[INFO] BSSID: {0}' -f $a.BSSID) }
        $bandL = $band.ToLowerInvariant()
        if ($bandL -match '6' -and $bandL -match 'ghz') {
            $lines += '[WARN] PC is on 6 GHz — console on 5 GHz of same SSID can make MITM one-sided'
        } elseif ($bandL -match '2\.4') {
            $lines += '[INFO] PC is on 2.4 GHz'
        } elseif ($bandL -match '5') {
            $lines += '[INFO] PC is on 5 GHz'
        }
    }
}
$lines += '------------------------------------------------------------------------'
$lines += ''
$lines += '--- Related programs ---'
foreach ($n in ($npcapApps + $winpcapApps + $nmapApps | Select-Object -Unique)) { $lines += "  $n" }
if (-not ($npcapApps + $winpcapApps + $nmapApps)) { $lines += '  (none matched)' }
$lines += ''
$lines += '--- IPv4 adapters (redacted) ---'
foreach ($a in $adapters) {
    $lines += ("  {0}: {1}" -f $a.InterfaceAlias, (Format-SafeIPv4 $a.IPAddress))
}
$lines += ''
$lines += '--- WinDivert paths ---'
if (-not $wdBundles.Count) { $lines += '  (no ZubCut install folder found)' }
foreach ($b in $wdBundles) {
    $lines += ("  {0}  dll={1} sys={2} complete={3}" -f $b.Dir, $b.Dll, $b.Sys, $b.Complete)
}
$lines += ''
$lines += '--- ARP sample (MAC + host only, first 40) ---'
$arp = arp -a | Select-Object -First 40
foreach ($l in $arp) {
    $safe = $l
    if ($safe -match '(\d+\.\d+\.\d+\.(\d+))') {
        $hostPart = $Matches[2]
        $safe = $safe -replace [regex]::Escape($Matches[1]), (".{0}" -f $hostPart)
    }
    $lines += "  $safe"
}
$lines += ''
$lines += '--- Recommended next steps ---'
if (-not $admin) { $lines += '  1. Re-run this script as Administrator (Quick check button / UAC).' }
if (-not $npcapOk) { $lines += '  2. Install Npcap from https://npcap.com/ (WinPcap API-compatible mode ON; enable Wi-Fi).' }
if (-not $npcapSvcOk) { $lines += '  3. Start Npcap service (or reboot after Npcap install).' }
if ($npcapAdminOnly -and -not $admin) { $lines += '  3b. Npcap AdminOnly is ON — run ZubCut as Administrator (or reinstall Npcap without AdminOnly).' }
if ($winpcapKey -or $winpcapApps.Count) {
    $lines += '  4. Uninstall WinPcap/Win10Pcap, reboot, keep Npcap only.'
}
if ($ipFwdOn) {
    $lines += '  5. IP forwarding is ON — restart ZubCut as Admin (or Kill OFF/ON) so Kill can fully cut.'
}
if (-not $gwMacOk) {
    $lines += '  6. Gateway MAC unknown — ping the router, confirm Npcap, pick the LAN adapter in Settings.'
}
if ($ifaceSaved -and -not $savedLive) {
    $lines += '  7. Settings adapter not live — open Settings, pick the connected Wi-Fi/Ethernet row, Apply, Rescan.'
}
if ($pcIp -and $gwPrimary -and -not $pcGwSame) {
    $lines += '  8. PC and gateway on different subnets — pick the LAN router adapter (not modem/VPN).'
}
if ($clumsy -and -not $hotspotReady) {
    $lines += '  9. Clumsy ON but Mobile Hotspot not ready — turn Mobile Hotspot ON in Settings, wait for 192.168.137.1 or 192.168.173.1, put PS5 on it, rescan.'
}
if ($clumsy -and $hotspotOn -and -not $dhcp67) {
    $lines += '  9b. Hotspot DHCP (UDP 67) down — known Win11 24H2/25H2 ICS bug on some builds; install latest Windows Update, restart services SharedAccess + icssvc, or set a static 192.168.137.x / 173.x on the console.'
    $lines += '  9c. Still no DHCP after 9b — some 24H2/25H2 builds break WcmSvc: in regedit HKLM\SYSTEM\CurrentControlSet\Services\WcmSvc remove WinHTTPAutoProxySvc from DependOnService, then restart WcmSvc + WlanSvc (community workaround; reboot if needed).'
    $lines += '  9d. icssvc crash / error 0x80070002 on 25H2 — install latest Windows Update; static console IP 192.168.137.x or 173.x (gw .1) can confirm routing until then.'
}
if ($clumsy -and -not $wdOk) {
    $lines += ' 10. Reinstall ZubCut with "Clumsy mode" checked (WinDivert missing).'
    $lines += ' 10b. If WinDivert.dll is present but driver fails — turn off Core Isolation Memory Integrity and/or Smart App Control, reboot, retry.'
}
if ($gateways.Count -gt 1) {
    $lines += ' 11. Multiple gateways (modem+router?) — pick the LAN router adapter in ZubCut Settings.'
}
$lines += ' 12. Wi-Fi 7 MLO — if LAN Kill fails while devices reach the router, disable MLO on the AP, prefer WPA2, or use Mobile Hotspot / Ethernet (ZC-MLO).'
$lines += '  Send this .txt screenshot / file to ZubCut support.'
$lines += '========================================================================'

$text = ($lines -join "`r`n")
Set-Content -Path $out -Value $text -Encoding UTF8
Write-Host $text
Write-Host ""
Write-Host "Saved: $out"
try { notepad $out } catch { Invoke-Item $out }
