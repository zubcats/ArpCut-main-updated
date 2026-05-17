# LEGACY: forces PC Wi-Fi uplink to 2.4 GHz (same band as hotspot). Prefer set_hotspot_2ghz.ps1
# (keeps PC on 5 GHz) or set_hotspot_2ghz_ethernet.ps1 (Ethernet internet + 2.4 GHz hotspot).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_hotspot_2ghz_full_result.txt'
function L([string]$m) { Add-Content -Path $log -Value $m -Encoding UTF8; Write-Host $m }
if (Test-Path $log) { Remove-Item $log -Force }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
L "=== Full 2.4 GHz hotspot fix (uplink + band) ==="
L "Administrator: $isAdmin"
if (-not $isAdmin) { L 'FAILED: Run as Administrator'; exit 1 }

. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

function Get-WifiUplinkChannel {
    $out = netsh wlan show interfaces 2>$null | Out-String
    if ($out -match 'Channel\s*:\s*(\d+)') { return [int]$Matches[1] }
    return 0
}

function Find-24GhzBssidForConnectedSsid {
    $ifaces = netsh wlan show interfaces 2>$null | Out-String
    if ($ifaces -notmatch 'SSID\s*:\s*(.+)\r?\n') { return $null }
    $ssid = $Matches[1].Trim()
    if (-not $ssid) { return $null }
    L "Connected SSID: $ssid"
    $scan = netsh wlan show networks mode=bssid 2>$null | Out-String
    $blocks = $scan -split '(?=SSID\s+\d+\s*:)'
    $ssidPat = [regex]::Escape($ssid)
    foreach ($block in $blocks) {
        if ($block -notmatch "SSID\s*(?:\d+\s*)?:\s*$ssidPat") { continue }
        $bestBssid = $null
        $bestSignal = -1
        $parts = $block -split 'BSSID \d+\s*:'
        foreach ($part in $parts) {
            if ($part -notmatch '([0-9a-f]{2}(?::[0-9a-f]{2}){5})') { continue }
            $bssid = $Matches[1]
            $ch = 0
            $sig = 0
            if ($part -match 'Channel\s*:\s*(\d+)') { $ch = [int]$Matches[1] }
            if ($part -match 'Signal\s*:\s*(\d+)') { $sig = [int]$Matches[1] }
            if ($ch -ge 1 -and $ch -le 14 -and $sig -gt $bestSignal) {
                $bestBssid = $bssid
                $bestSignal = $sig
            }
        }
        if ($bestBssid) {
            L "Best 2.4 GHz BSSID for $ssid : $bestBssid (signal $bestSignal%)"
            return @{ Ssid = $ssid; Bssid = $bestBssid }
        }
    }
    return $null
}

function Move-UplinkTo24Ghz {
    $ch = Get-WifiUplinkChannel
    L "Current uplink channel: $ch"
    if ($ch -ge 1 -and $ch -le 14) {
        L 'Uplink already on 2.4 GHz — no Wi-Fi switch needed.'
        return $true
    }
    $target = Find-24GhzBssidForConnectedSsid
    if (-not $target) {
        L 'WARNING: No 2.4 GHz BSSID found for current SSID. Use Ethernet to router OR connect PC to 2.4 GHz Wi-Fi first.'
        return $false
    }
    $iface = (Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Wireless LAN' -and $_.Status -eq 'Up' } | Select-Object -First 1).Name
    if (-not $iface) { $iface = 'Wi-Fi' }
    L "Stopping hotspot before Wi-Fi band switch..."
    Stop-MobileHotspotIfOn | Out-Null
    Start-Sleep -Seconds 2
    L "Connecting $iface to $($target.Ssid) via 2.4 GHz BSSID $($target.Bssid)..."
    netsh wlan disconnect interface="$iface" 2>$null | Out-Null
    Start-Sleep -Seconds 2
    $r = netsh wlan connect name="$($target.Ssid)" ssid="$($target.Ssid)" interface="$iface" bss="$($target.Bssid)" 2>&1 | Out-String
    L $r.Trim()
    Start-Sleep -Seconds 8
    $ch2 = Get-WifiUplinkChannel
    L "Uplink channel after switch: $ch2"
    return ($ch2 -ge 1 -and $ch2 -le 14)
}

try {
    $uplinkOk = Move-UplinkTo24Ghz
    if (-not $uplinkOk) {
        L 'Continuing with hotspot band API anyway (Settings may still show 5 GHz on single-radio USB).'
    }
    if (-not (Ensure-MobileHotspot2GhzBand)) { throw 'Ensure-MobileHotspot2GhzBand failed' }
    Start-MobileHotspotAfter2GhzConfig | Out-Null
    Start-Sleep -Seconds 6

    $ch = Get-WifiUplinkChannel
    $mgr = Get-TetheringManager
    $band = if ($mgr) { Get-MobileHotspotBandLabel $mgr } else { '' }
    L "Final: uplink channel=$ch hotspot band=$band state=$($mgr.TetheringOperationalState)"

    if ($band -match 'TwoPointFour' -and $ch -ge 1 -and $ch -le 14) {
        L 'SUCCESS: PC on 2.4 GHz Wi-Fi and hotspot configured for 2.4 GHz. Check Settings — warning should clear.'
        exit 0
    }
    if ($band -match 'TwoPointFour') {
        L 'PARTIAL: Hotspot API is 2.4 GHz but PC uplink may still be 5 GHz — Settings can still show 5 GHz only.'
        exit 0
    }
    L 'Check Settings -> Mobile hotspot. If still 5 GHz only, plug Ethernet to router for PC internet.'
    exit 2
} catch {
    L "ERROR: $($_.Exception.Message)"
    exit 1
}
