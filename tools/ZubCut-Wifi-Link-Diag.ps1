# ZubCut Wi-Fi Link Diagnostic (this PC only) — run elevated via ZubCut Logs.
# Writes ZubCut-Wifi-Link-*.txt under Desktop\ZubCut Diagnostics (not the script).

$ErrorActionPreference = 'SilentlyContinue'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$desktop = [Environment]::GetFolderPath('Desktop')
$diagDir = Join-Path $desktop 'ZubCut Diagnostics'
if (-not (Test-Path -LiteralPath $diagDir)) {
    New-Item -ItemType Directory -Path $diagDir -Force | Out-Null
}
$out = Join-Path $diagDir "ZubCut-Wifi-Link-$stamp.txt"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-BandFromChannel([int]$ch) {
    if ($ch -le 0) { return $null }
    if ($ch -le 14) { return '2.4 GHz' }
    if ($ch -gt 177) { return '6 GHz' }
    return '5 GHz'
}

function Get-SecurityStrength([string]$auth) {
    $a = ($auth | Out-String).Trim().ToLowerInvariant()
    if (-not $a) { return 'unknown' }
    if ($a -match 'wpa3|wpa2') { return 'strong' }
    if ($a -eq 'open' -or $a -eq 'none' -or $a -match 'wep') { return 'weak' }
    if ($a -match '\bwpa\b' -and $a -notmatch 'wpa2' -and $a -notmatch 'wpa3') { return 'weak' }
    return 'unknown'
}

$admin = Test-IsAdmin
$raw = netsh wlan show interfaces | Out-String

# Parse interface blocks
$adapters = @()
$current = @{}
foreach ($line in ($raw -split "`r?`n")) {
    if ($line -match '^\s*Name\s*:\s*(.+)\s*$') {
        if ($current.Count -gt 0 -and $current.ContainsKey('Name')) {
            $adapters += ,([pscustomobject]$current)
        }
        $current = @{ Name = $Matches[1].Trim() }
        continue
    }
    if ($line -match '^\s+(\S.*?)\s*:\s*(.*?)\s*$') {
        $key = ($Matches[1] -replace '\s+', ' ').Trim()
        $val = $Matches[2].Trim()
        if ($key) { $current[$key] = $val }
    }
}
if ($current.Count -gt 0 -and $current.ContainsKey('Name')) {
    $adapters += ,([pscustomobject]$current)
}

# Ethernet uplink aliases (best-effort)
$ethNames = @()
try {
    $ethNames = @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            ForEach-Object {
                $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
                if ($a -and $a.Status -eq 'Up' -and ($a.MediaType -match '802.3|Ethernet')) {
                    $_.InterfaceAlias
                }
            } | Select-Object -Unique
    )
} catch {}

$lines = @()
$lines += '========================================================================'
$lines += ' ZubCut Wi-Fi Link (this PC only)'
$lines += '========================================================================'
$lines += ("Generated: {0}" -f (Get-Date).ToString('u'))
$lines += ("Administrator: {0}" -f $(if ($admin) { 'yes' } else { 'NO — approve UAC / Run as administrator' }))
$lines += 'Victim/PS5 band & security cannot be read from the LAN — PC link only.'
$lines += 'No LAN IPs are listed in this report.'
$lines += ''
$lines += '>>> SCREENSHOT THIS SUMMARY <<<'
$lines += '------------------------------------------------------------------------'
$lines += ("[{0}] Running as Administrator" -f $(if ($admin) { 'PASS' } else { 'FAIL' }))

$connected = @($adapters | Where-Object {
        $st = [string]$_.State
        $ssid = [string]$_.SSID
        ($st -eq 'connected') -and ($ssid.Trim().Length -gt 0)
    })

if ($adapters.Count -eq 0) {
    $lines += '[FAIL] No Wi-Fi interface info (netsh wlan returned nothing)'
} elseif ($connected.Count -eq 0) {
    if ($ethNames.Count -gt 0) {
        $lines += ('[WARN] No connected Wi-Fi link — Ethernet uplink is up: {0}' -f ($ethNames -join ', '))
    } else {
        $lines += '[WARN] No connected Wi-Fi link — Wi-Fi may be off (no Ethernet uplink detected)'
    }
    foreach ($a in $adapters) {
        $lines += ('[INFO] {0}: state={1}' -f $a.Name, $a.State)
    }
} else {
    foreach ($a in $connected) {
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
        $strength = Get-SecurityStrength $auth

        $lines += ('[PASS] Connected: {0}' -f $a.Name)
        $lines += ('[INFO] SSID: {0}' -f $ssid)
        $lines += ('[INFO] Band: {0} (channel {1})' -f $band, $(if ($ch -gt 0) { $ch } else { '?' }))
        $lines += ('[INFO] Security: {0} / {1}' -f $auth, $cipher)
        if ($strength -eq 'weak') {
            $lines += '[WARN] Weak/open Wi-Fi security — prefer WPA2-Personal or WPA3-Personal'
        } elseif ($strength -eq 'strong') {
            $lines += '[PASS] Security looks like WPA2/WPA3'
        }
        $lines += ('[INFO] Radio: {0}  Signal: {1}' -f $radio, $sig)
        $lines += ('[INFO] Rates: rx {0} Mbps / tx {1} Mbps' -f $rx, $tx)
        if ($a.GUID) { $lines += ('[INFO] Adapter GUID: {0}' -f $a.GUID) }
        if ($a.BSSID) { $lines += ('[INFO] BSSID: {0}' -f $a.BSSID) }
        $bandL = $band.ToLowerInvariant()
        if ($bandL -match '6' -and $bandL -match 'ghz') {
            $lines += '[WARN] PC is on 6 GHz — if the console is on 5 GHz of the same SSID, MITM can be one-sided; prefer both on the same 5 GHz BSS when possible.'
        } elseif ($bandL -match '2\.4') {
            $lines += '[INFO] PC is on 2.4 GHz'
        } elseif ($bandL -match '5') {
            $lines += '[INFO] PC is on 5 GHz'
        }
    }
    if ($ethNames.Count -gt 0) {
        $lines += ('[INFO] Ethernet also up: {0}' -f ($ethNames -join ', '))
    }
}

$lines += '------------------------------------------------------------------------'
$lines += ''
$lines += '--- All WLAN interfaces ---'
if ($adapters.Count -eq 0) { $lines += '  (none)' }
foreach ($a in $adapters) {
    $ch = '-'
    if ([string]$a.Channel -match '(\d+)') { $ch = $Matches[1] }
    $band = [string]$a.Band
    if (-not $band -and $ch -ne '-') { $band = Get-BandFromChannel ([int]$ch) }
    if (-not $band) { $band = '-' }
    $lines += ('  {0}: state={1} ssid={2} band={3} ch={4} auth={5}' -f `
        $a.Name, $a.State, $(if ($a.SSID) { $a.SSID } else { '-' }), $band, $ch, `
        $(if ($a.Authentication) { $a.Authentication } else { '-' }))
}
$lines += ''
$lines += '--- Recommended next steps ---'
if (-not $admin) { $lines += '  1. Re-run from ZubCut Logs (approve UAC) so this check is Administrator.' }
$lines += '  Send this .txt screenshot / file to ZubCut support.'
$lines += '  This report is the ZubCut PC Wi-Fi link only (not the console).'
$lines += '========================================================================'
$lines += ''
$lines += '--- Raw: netsh wlan show interfaces ---'
$lines += $raw.TrimEnd()
$lines += '========================================================================'

$text = ($lines -join "`r`n")
Set-Content -Path $out -Value $text -Encoding UTF8
Write-Host $text
Write-Host ""
Write-Host "Saved: $out"
try { notepad $out } catch { Invoke-Item $out }
