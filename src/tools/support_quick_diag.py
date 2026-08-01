"""Launch the ZubCut Quick Network Diagnostic in elevated PowerShell.

This is the same checks friends run via ``tools/ZubCut-Quick-Network-Diag.ps1`` /
the Admin PowerShell paste — Npcap, WinPcap, hotspot, WinDivert, adapters, ARP.
Kept in-app (not the standalone Python ``zubcut_support_diag.py``) so installed
users do not need a repo checkout or Python.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Keep in sync with tools/ZubCut-Quick-Network-Diag.ps1 (tested).
QUICK_DIAG_PS1_NAME = 'ZubCut-Quick-Network-Diag.ps1'

_EMBEDDED_QUICK_DIAG_PS1 = r"""# ZubCut Quick Network Diagnostic (no Python / no repo required)
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

function Test-SameSlash24([string]$ipA, [string]$ipB) {
    if ($ipA -notmatch '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') { return $false }
    $a1 = $Matches[1]; $a2 = $Matches[2]; $a3 = $Matches[3]
    if ($ipB -notmatch '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') { return $false }
    $b1 = $Matches[1]; $b2 = $Matches[2]; $b3 = $Matches[3]
    return ($a1 -eq $b1 -and $a2 -eq $b2 -and $a3 -eq $b3)
}

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

$admin = Test-IsAdmin
$npcapPath = 'C:\Windows\SysWOW64\Npcap'
$npcapOk = Test-Path $npcapPath
$npcapSvc = Get-Service -Name 'npcap', 'npf' -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq 'Running' } |
    Select-Object -First 1
$npcapSvcOk = $null -ne $npcapSvc
$npcapSvcName = if ($npcapSvc) { $npcapSvc.Name } else { '(none running)' }

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
$icsGw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } |
    Select-Object -First 1
$hasIcsGw = $null -ne $icsGw
$hotspotReady = $hotspotOn -and $hasIcsGw
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

# PC vs gateway same /24 (using first non-APIPA adapter IP if possible)
$pcIp = $null
foreach ($a in $adapters) {
    if ($a.IPAddress -and ($a.IPAddress -notlike '169.254.*') -and ($a.IPAddress -notlike '192.168.137.*')) {
        $pcIp = [string]$a.IPAddress
        break
    }
}
if (-not $pcIp -and $savedIp) { $pcIp = $savedIp }
$pcGwSame = $false
if ($pcIp -and $gwPrimary) {
    $pcGwSame = Test-SameSlash24 $pcIp $gwPrimary
}

$lines = @()
$lines += '========================================================================'
$lines += ' ZubCut Quick Network Diagnostic (PowerShell)'
$lines += '========================================================================'
$lines += ("Generated: {0}" -f (Get-Date).ToString('u'))
$lines += ("Administrator: {0}" -f $(if ($admin) { 'yes' } else { 'NO — approve UAC / Run as administrator' }))
$lines += 'IPs in SUMMARY are masked with x for screenshot privacy.'
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
$lines += ("[{0}] Npcap folder present ({1})" -f $(if ($npcapOk) { 'PASS' } else { 'FAIL' }), $npcapPath)
$lines += ("[{0}] Npcap/NPF service running ({1})" -f $(if ($npcapSvcOk) { 'PASS' } else { 'FAIL' }), $npcapSvcName)
$lines += ("[{0}] WinPcap uninstall key absent" -f $(if ($winpcapKey) { 'FAIL' } else { 'PASS' }))
$lines += ("[{0}] WinPcap/Win10Pcap not in Apps list" -f $(if ($winpcapApps.Count) { 'FAIL' } else { 'PASS' }))
$lines += ("[{0}] IP forwarding off (Kill full-cut)" -f $(if ($ipFwdOn) { 'FAIL' } else { 'PASS' }))
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
    $lines += ("[{0}] PC and gateway on same /24" -f $(if ($pcGwSame) { 'PASS' } else { 'FAIL' }))
    $lines += ("[INFO] PC {0}  GW {1}" -f (Format-SafeIPv4 $pcIp), (Format-SafeIPv4 $gwPrimary))
} else {
    $lines += '[WARN] Could not compare PC IP vs gateway subnet'
}
if ($hotspotOn) {
    if ($hasIcsGw) {
        $lines += '[PASS] Mobile Hotspot ON (ICS 192.168.137.1)'
    } else {
        $lines += '[WARN] Mobile Hotspot ON but ICS 192.168.137.1 missing — wait or toggle hotspot'
    }
} elseif ($clumsy) {
    $lines += '[WARN] Mobile Hotspot OFF (Clumsy ON — turn Mobile Hotspot on in Settings)'
} else {
    $lines += '[INFO] Mobile Hotspot OFF (OK when Clumsy is off)'
}
if (-not $hotspotOn -and $hasIcsGw) {
    $lines += '[INFO] Leftover ICS 192.168.137.1 still present (Settings hotspot is off)'
}
$lines += ("[{0}] WinDivert bundle under ZubCut" -f $(if ($wdOk) { 'PASS' } else { 'WARN' }))
$gwSafe = @($gateways | ForEach-Object { Format-SafeIPv4 $_ })
$lines += ("[INFO] Default gateways: {0}" -f ($(if ($gwSafe) { $gwSafe -join ', ' } else { '(none)' })))
if ($gwMacOk) { $lines += ("[INFO] Gateway MAC: {0}" -f $gwMac) }
$lines += ("[INFO] Clumsy mode (settings): {0}" -f ($(if ($null -eq $clumsy) { '(unknown)' } else { $clumsy })))
$lines += ("[INFO] Saved adapter (settings): {0}" -f ($(if ($ifaceSaved) { $ifaceSaved } else { '(not set)' })))
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
if (-not $npcapOk) { $lines += '  2. Install Npcap from https://npcap.com/ (enable Wi-Fi adapter).' }
if (-not $npcapSvcOk) { $lines += '  3. Start Npcap service (or reboot after Npcap install).' }
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
    $lines += '  9. Clumsy ON but Mobile Hotspot not ready — turn Mobile Hotspot ON in Settings, wait for 192.168.137.1, put PS5 on it, rescan.'
}
if ($clumsy -and -not $wdOk) {
    $lines += ' 10. Reinstall ZubCut with "Clumsy mode" checked (WinDivert missing).'
}
if ($gateways.Count -gt 1) {
    $lines += ' 11. Multiple gateways (modem+router?) — pick the LAN router adapter in ZubCut Settings.'
}
$lines += '  Send this .txt screenshot / file to ZubCut support.'
$lines += '========================================================================'

$text = ($lines -join "`r`n")
Set-Content -Path $out -Value $text -Encoding UTF8
Write-Host $text
Write-Host ""
Write-Host "Saved: $out"
try { notepad $out } catch { Invoke-Item $out }
"""


def repo_quick_diag_ps1_path() -> Path | None:
    """``tools/ZubCut-Quick-Network-Diag.ps1`` when running from a source checkout."""
    here = Path(__file__).resolve()
    # src/tools/support_quick_diag.py -> repo root
    candidates = [
        here.parents[2] / 'tools' / QUICK_DIAG_PS1_NAME,
        Path.cwd() / 'tools' / QUICK_DIAG_PS1_NAME,
    ]
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def quick_diag_ps1_text() -> str:
    """Prefer the repo script on disk; fall back to the in-app embedded copy."""
    disk = repo_quick_diag_ps1_path()
    if disk is not None:
        try:
            return disk.read_text(encoding='utf-8')
        except OSError:
            pass
    return _EMBEDDED_QUICK_DIAG_PS1


def materialize_quick_diag_ps1() -> Path:
    """
    Overwrite a single temp runner script for elevated PowerShell.

    Reports go to Desktop\\ZubCut Diagnostics; this ``.ps1`` stays out of that
    folder (one reused temp file, not a pile of copies).
    """
    text = quick_diag_ps1_text()
    if not text.strip().endswith('\n'):
        text = text.rstrip('\r\n') + '\n'
    dest_dir = Path(tempfile.gettempdir()) / 'ZubCut'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / QUICK_DIAG_PS1_NAME
    dest.write_text(text, encoding='utf-8', newline='\n')
    return dest


def launch_quick_network_diag_elevated(*, elevate=None) -> tuple[bool, str]:
    """
    Open Admin PowerShell, run the quick network diagnostic, open the report.

    Returns ``(ok, status_message)`` for the Logs window status strip.
    ``elevate`` is injectable for tests (defaults to ``spawn_windows_elevated``).
    Reports land in Desktop\\ZubCut Diagnostics.
    """
    if not sys.platform.startswith('win'):
        return False, 'Quick check is Windows-only.'
    try:
        script = materialize_quick_diag_ps1()
    except Exception as exc:
        return False, f'Could not prepare Quick check: {exc}'
    from tools.diag_elevate import launch_ps1_elevated

    return launch_ps1_elevated(script, elevate=elevate, tool_label='Quick check')
