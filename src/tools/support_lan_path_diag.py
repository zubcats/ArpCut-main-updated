"""Launch the ZubCut LAN path diagnostic in elevated PowerShell (Logs → LAN path)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

LAN_PATH_PS1_NAME = 'ZubCut-Lan-Path-Diag.ps1'

# Keep in sync with tools/ZubCut-Lan-Path-Diag.ps1 (tested).
_EMBEDDED_LAN_PATH_PS1 = r"""# ZubCut LAN Path Diagnostic — elevated via ZubCut Logs.
# Focus: home LAN Kill readiness (not Clumsy hotspot).
# Writes ZubCut-Lan-Path-*.txt under Desktop\ZubCut Diagnostics.

$ErrorActionPreference = 'SilentlyContinue'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$desktop = [Environment]::GetFolderPath('Desktop')
$diagDir = Join-Path $desktop 'ZubCut Diagnostics'
if (-not (Test-Path -LiteralPath $diagDir)) {
    New-Item -ItemType Directory -Path $diagDir -Force | Out-Null
}
$out = Join-Path $diagDir "ZubCut-Lan-Path-$stamp.txt"
# Surface unexpected failures (otherwise the window can flash closed with no Notepad).
trap {
    try {
        $errFile = Join-Path $diagDir ("ZubCut-Lan-Path-ERROR-{0}.txt" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
        @(
            'ZubCut LAN Path failed.',
            $_.Exception.Message,
            ($_.ScriptStackTrace | Out-String)
        ) | Set-Content -Path $errFile -Encoding UTF8
        notepad $errFile
    } catch {}
    break
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Format-SafeIPv4([string]$ip) {
    if (-not $ip) { return '(ip)' }
    $ip = $ip.Trim()
    if ($ip -match '^(192)\.(168)\.(137)\.(\d+)$') { return '192.168.137.x' }
    if ($ip -match '^(169)\.(254)\.(\d+)\.(\d+)$') { return '169.254.x.x' }
    if ($ip -match '^(127)\.(\d+)\.(\d+)\.(\d+)$') { return ("127.x.x.{0}" -f $Matches[4]) }
    if ($ip -match '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') {
        $a = [int]$Matches[1]; $b = [int]$Matches[2]; $d = [int]$Matches[4]
        if (($a -eq 192) -and ($b -eq 168)) { return ("192.168.x.{0}" -f $d) }
        if ($a -eq 10) { return ("10.x.x.{0}" -f $d) }
        if (($a -eq 172) -and ($b -ge 16) -and ($b -le 31)) { return ("172.x.x.{0}" -f $d) }
        return ("x.x.x.{0}" -f $d)
    }
    return '(ip)'
}

function Test-SameSlash24([string]$ipA, [string]$ipB) {
    if ($ipA -notmatch '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') { return $false }
    $a1 = $Matches[1]; $a2 = $Matches[2]; $a3 = $Matches[3]
    if ($ipB -notmatch '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') { return $false }
    return ($a1 -eq $Matches[1] -and $a2 -eq $Matches[2] -and $a3 -eq $Matches[3])
}

$admin = Test-IsAdmin
$ipcfg = ipconfig | Out-String
$gateways = [regex]::Matches(
    $ipcfg,
    '(?i)(?:Default Gateway|Passerelle par d[eé]faut|Standardgateway|Puerta de enlace predeterminada|Gateway predefinito)[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})'
) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
try {
    $routeGws = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Where-Object { $_.NextHop -and $_.NextHop -ne '0.0.0.0' } |
        Select-Object -ExpandProperty NextHop -Unique
    if ($routeGws) { $gateways = @($routeGws | Sort-Object -Unique) }
} catch {}

$adapters = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' } |
    Select-Object InterfaceAlias, IPAddress

$settingsPath = Join-Path $env:APPDATA 'ZubCut\zubcut.json'
$clumsy = $null
$ifaceSaved = $null
if (Test-Path $settingsPath) {
    try {
        $js = Get-Content $settingsPath -Raw | ConvertFrom-Json
        if ($js -isnot [System.Array]) {
            $clumsy = $js.clumsy_mode
            $ifaceSaved = $js.iface
        }
    } catch {}
}

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

$gwPrimary = if ($gateways) { [string]$gateways[0] } else { $null }
$gwMac = $null
$gwMacOk = $false
if ($gwPrimary) {
    $arpAll = arp -a | Out-String
    $macRx = [regex]::Match($arpAll, [regex]::Escape($gwPrimary) + '\s+([0-9a-fA-F\-]{17})')
    if ($macRx.Success) {
        $gwMac = $macRx.Groups[1].Value
        $gwMacOk = $gwMac -and ($gwMac -notmatch '^(ff-ff-ff-ff-ff-ff|00-00-00-00-00-00)$')
    }
}

$pcIp = $null
foreach ($a in $adapters) {
    if ($a.IPAddress -and ($a.IPAddress -notlike '169.254.*') -and ($a.IPAddress -notlike '192.168.137.*')) {
        $pcIp = [string]$a.IPAddress
        break
    }
}
if (-not $pcIp -and $savedIp) { $pcIp = $savedIp }
$pcGwSame = $false
if ($pcIp -and $gwPrimary) { $pcGwSame = Test-SameSlash24 $pcIp $gwPrimary }

$ipFwd = 0
try {
    $ipFwd = [int](Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' `
        -Name 'IPEnableRouter' -ErrorAction SilentlyContinue).IPEnableRouter
} catch { $ipFwd = 0 }
$ipFwdOn = $ipFwd -ne 0

$lines = @()
$lines += '========================================================================'
$lines += ' ZubCut LAN Path Diagnostic'
$lines += '========================================================================'
$lines += ("Generated: {0}" -f (Get-Date).ToString('u'))
$lines += ("Administrator: {0}" -f $(if ($admin) { 'yes' } else { 'NO — approve UAC' }))
$lines += 'IPs in SUMMARY are masked with x for screenshot privacy.'
$lines += 'This report is for home LAN Kill (same Wi-Fi/Ethernet as the console).'
$lines += ''
$lines += '>>> SCREENSHOT THIS SUMMARY <<<'
$lines += '------------------------------------------------------------------------'
if ($clumsy) {
    $lines += '[WARN] Settings Clumsy is ON — LAN Kill path may not apply; use Hotspot path or turn Clumsy off'
} else {
    $lines += '[INFO] Active path: LAN Kill (Clumsy OFF)'
}
$lines += ("[{0}] Running as Administrator" -f $(if ($admin) { 'PASS' } else { 'FAIL' }))
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
$lines += ("[{0}] Gateway MAC known (MITM)" -f $(if ($gwMacOk) { 'PASS' } else { 'FAIL' }))
if ($pcIp -and $gwPrimary) {
    $lines += ("[{0}] PC and gateway on same /24" -f $(if ($pcGwSame) { 'PASS' } else { 'FAIL' }))
    $lines += ("[INFO] PC {0}  GW {1}" -f (Format-SafeIPv4 $pcIp), (Format-SafeIPv4 $gwPrimary))
} else {
    $lines += '[WARN] Could not compare PC IP vs gateway subnet'
}
$lines += ("[{0}] IP forwarding off (Kill full-cut)" -f $(if ($ipFwdOn) { 'FAIL' } else { 'PASS' }))
if ($gwMacOk) { $lines += ("[INFO] Gateway MAC: {0}" -f $gwMac) }
$lines += ("[INFO] Saved adapter: {0}" -f ($(if ($ifaceSaved) { $ifaceSaved } else { '(not set)' })))
$lines += ("[INFO] Clumsy mode (settings): {0}" -f ($(if ($null -eq $clumsy) { '(unknown)' } else { $clumsy })))
$lines += '------------------------------------------------------------------------'
$lines += ''
$lines += '--- Recommended next steps ---'
if (-not $admin) { $lines += '  1. Re-run from ZubCut Logs and approve UAC.' }
if ($ifaceSaved -and -not $savedLive) {
    $lines += '  2. Settings → pick the connected Wi-Fi/Ethernet row → Apply → Rescan.'
}
if (-not $gwMacOk) {
    $lines += '  3. Gateway MAC unknown — ping the router, confirm Npcap, pick the LAN adapter.'
}
if ($pcIp -and $gwPrimary -and -not $pcGwSame) {
    $lines += '  4. PC and gateway on different subnets — pick the LAN router adapter (not modem/VPN).'
}
if ($ipFwdOn) {
    $lines += '  5. IP forwarding is ON — restart ZubCut as Admin so Kill can fully cut.'
}
if ($clumsy) {
    $lines += '  6. Clumsy ON — for LAN Kill turn Clumsy off in Settings; for hotspot use Hotspot path.'
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


def repo_lan_path_ps1_path() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / 'tools' / LAN_PATH_PS1_NAME,
        Path.cwd() / 'tools' / LAN_PATH_PS1_NAME,
    ]
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def lan_path_ps1_text() -> str:
    disk = repo_lan_path_ps1_path()
    if disk is not None:
        try:
            return disk.read_text(encoding='utf-8')
        except OSError:
            pass
    return _EMBEDDED_LAN_PATH_PS1


def materialize_lan_path_ps1() -> Path:
    from tools.diag_elevate import write_ps1_runner

    dest_dir = Path(tempfile.gettempdir()) / 'ZubCut'
    dest = dest_dir / LAN_PATH_PS1_NAME
    return write_ps1_runner(dest, lan_path_ps1_text())


def launch_lan_path_diag(*, elevate=None) -> tuple[bool, str]:
    if not sys.platform.startswith('win'):
        return False, 'LAN path is Windows-only.'
    try:
        script = materialize_lan_path_ps1()
    except Exception as exc:
        return False, f'Could not prepare LAN path: {exc}'
    from tools.diag_elevate import launch_ps1_elevated

    return launch_ps1_elevated(script, elevate=elevate, tool_label='LAN path')
