"""Launch the ZubCut Hotspot path diagnostic in elevated PowerShell (Logs → Hotspot path)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HOTSPOT_PATH_PS1_NAME = 'ZubCut-Hotspot-Path-Diag.ps1'

# Keep in sync with tools/ZubCut-Hotspot-Path-Diag.ps1 (tested).
_EMBEDDED_HOTSPOT_PATH_PS1 = r"""# ZubCut Hotspot Path Diagnostic — elevated via ZubCut Logs.
# Focus: Clumsy Mobile Hotspot readiness (not home LAN Kill).
# Writes ZubCut-Hotspot-Path-*.txt under Desktop\ZubCut Diagnostics.

$ErrorActionPreference = 'SilentlyContinue'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$desktop = [Environment]::GetFolderPath('Desktop')
$diagDir = Join-Path $desktop 'ZubCut Diagnostics'
if (-not (Test-Path -LiteralPath $diagDir)) {
    New-Item -ItemType Directory -Path $diagDir -Force | Out-Null
}
$out = Join-Path $diagDir "ZubCut-Hotspot-Path-$stamp.txt"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-MobileHotspotOn {
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

function Format-SafeIPv4([string]$ip) {
    if (-not $ip) { return '(ip)' }
    $ip = $ip.Trim()
    if ($ip -match '^(192)\.(168)\.(137)\.(\d+)$') { return '192.168.137.x' }
    if ($ip -match '^(169)\.(254)\.(\d+)\.(\d+)$') { return '169.254.x.x' }
    if ($ip -match '^(\d+)\.(\d+)\.(\d+)\.(\d+)$') {
        $a = [int]$Matches[1]; $b = [int]$Matches[2]; $d = [int]$Matches[4]
        if (($a -eq 192) -and ($b -eq 168)) { return ("192.168.x.{0}" -f $d) }
        if ($a -eq 10) { return ("10.x.x.{0}" -f $d) }
        return ("x.x.x.{0}" -f $d)
    }
    return '(ip)'
}

$admin = Test-IsAdmin
$hotspotOn = Test-MobileHotspotOn
$icsGw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } |
    Select-Object -First 1
$hasIcsGw = $null -ne $icsGw
$hotspotReady = $hotspotOn -and $hasIcsGw

$dhcp67 = $false
try {
    $dhcp67 = [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue)
} catch { $dhcp67 = $false }

$clients137 = @(
    Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -like '192.168.137.*' -and
            $_.IPAddress -ne '192.168.137.1' -and
            $_.State -in @('Reachable', 'Stale', 'Permanent', 'Probe', 'Delay')
        }
)
$clientCount = $clients137.Count

$zubcutDirs = @(
    (Join-Path $env:ProgramFiles 'ZubCut'),
    (Join-Path ${env:ProgramFiles(x86)} 'ZubCut'),
    (Join-Path $env:LOCALAPPDATA 'ZubCut')
) | Where-Object { $_ -and (Test-Path $_) }
$wdOk = $false
foreach ($d in $zubcutDirs) {
    $wd = Join-Path $d 'windivert'
    if ((Test-Path (Join-Path $wd 'WinDivert.dll')) -and (Test-Path (Join-Path $wd 'WinDivert64.sys'))) {
        $wdOk = $true
        break
    }
}

$settingsPath = Join-Path $env:APPDATA 'ZubCut\zubcut.json'
$clumsy = $null
if (Test-Path $settingsPath) {
    try {
        $js = Get-Content $settingsPath -Raw | ConvertFrom-Json
        if ($js -isnot [System.Array]) { $clumsy = $js.clumsy_mode }
    } catch {}
}

$lines = @()
$lines += '========================================================================'
$lines += ' ZubCut Hotspot Path Diagnostic'
$lines += '========================================================================'
$lines += ("Generated: {0}" -f (Get-Date).ToString('u'))
$lines += ("Administrator: {0}" -f $(if ($admin) { 'yes' } else { 'NO — approve UAC' }))
$lines += 'IPs in SUMMARY are masked with x for screenshot privacy.'
$lines += 'This report is for Clumsy mode (console on PC Mobile Hotspot).'
$lines += ''
$lines += '>>> SCREENSHOT THIS SUMMARY <<<'
$lines += '------------------------------------------------------------------------'
if ($clumsy) {
    if ($hotspotReady) {
        $lines += '[INFO] Active path: Clumsy hotspot (Clumsy ON, Mobile Hotspot ready)'
    } else {
        $lines += '[INFO] Active path: Clumsy hotspot (Clumsy ON — hotspot not ready yet)'
    }
} else {
    $lines += '[INFO] Active path: LAN Kill (Clumsy OFF) — Hotspot path not required'
}
$lines += ("[{0}] Running as Administrator" -f $(if ($admin) { 'PASS' } else { 'FAIL' }))
$lines += ("[{0}] Clumsy mode ON in Settings" -f $(if ($clumsy) { 'PASS' } else { 'WARN' }))
if ($hotspotOn) {
    if ($hasIcsGw) {
        $lines += '[PASS] Mobile Hotspot ON (ICS 192.168.137.1)'
    } else {
        $lines += '[WARN] Mobile Hotspot ON but ICS 192.168.137.1 missing — wait or toggle hotspot'
    }
} else {
    if ($clumsy) {
        $lines += '[WARN] Mobile Hotspot OFF — turn it ON in Windows Settings'
    } else {
        $lines += '[INFO] Mobile Hotspot OFF (OK when Clumsy is off)'
    }
}
if (-not $hotspotOn -and $hasIcsGw) {
    $lines += '[INFO] Leftover ICS 192.168.137.1 still present (Settings hotspot is off)'
}
$lines += ("[{0}] Hotspot DHCP listening (UDP 67)" -f $(if ($dhcp67) { 'PASS' } else { $(if ($clumsy -and $hotspotOn) { 'WARN' } else { 'INFO' }) }))
if ($clientCount -gt 0) {
    $lines += ("[PASS] Hotspot client(s) seen on 192.168.137.x: {0}" -f $clientCount)
} elseif ($clumsy -and $hotspotOn) {
    $lines += '[WARN] No hotspot client seen — put PS5 on this PC hotspot Wi-Fi, wait, rescan'
} else {
    $lines += '[INFO] No hotspot client on 192.168.137.x'
}
$lines += ("[{0}] WinDivert bundle under ZubCut" -f $(if ($wdOk) { 'PASS' } else { $(if ($clumsy) { 'FAIL' } else { 'WARN' }) }))
$lines += ("[INFO] Clumsy mode (settings): {0}" -f ($(if ($null -eq $clumsy) { '(unknown)' } else { $clumsy })))
if ($hasIcsGw) { $lines += ('[INFO] ICS gateway: {0}' -f (Format-SafeIPv4 '192.168.137.1')) }
$lines += '------------------------------------------------------------------------'
$lines += ''
$lines += '--- Recommended next steps ---'
if (-not $admin) { $lines += '  1. Re-run from ZubCut Logs and approve UAC.' }
if (-not $clumsy) {
    $lines += '  2. Clumsy is OFF — enable Clumsy mode in Settings only if using PC Mobile Hotspot.'
}
if ($clumsy -and -not $hotspotOn) {
    $lines += '  3. Turn Mobile Hotspot ON in Windows Settings, wait for 192.168.137.1.'
}
if ($clumsy -and $hotspotOn -and -not $hasIcsGw) {
    $lines += '  4. Hotspot ON but no 192.168.137.1 — toggle hotspot OFF 15s, ON again.'
}
if ($clumsy -and $hotspotOn -and $clientCount -eq 0) {
    $lines += '  5. Connect the console to this PC hotspot SSID, then Rescan in ZubCut.'
}
if ($clumsy -and -not $wdOk) {
    $lines += '  6. Reinstall ZubCut with Clumsy mode checked (WinDivert missing).'
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


def repo_hotspot_path_ps1_path() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / 'tools' / HOTSPOT_PATH_PS1_NAME,
        Path.cwd() / 'tools' / HOTSPOT_PATH_PS1_NAME,
    ]
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def hotspot_path_ps1_text() -> str:
    disk = repo_hotspot_path_ps1_path()
    if disk is not None:
        try:
            return disk.read_text(encoding='utf-8')
        except OSError:
            pass
    return _EMBEDDED_HOTSPOT_PATH_PS1


def materialize_hotspot_path_ps1() -> Path:
    text = hotspot_path_ps1_text()
    if not text.strip().endswith('\n'):
        text = text.rstrip('\r\n') + '\n'
    dest_dir = Path(tempfile.gettempdir()) / 'ZubCut'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / HOTSPOT_PATH_PS1_NAME
    dest.write_text(text, encoding='utf-8', newline='\n')
    return dest


def launch_hotspot_path_diag(*, elevate=None) -> tuple[bool, str]:
    if not sys.platform.startswith('win'):
        return False, 'Hotspot path is Windows-only.'
    try:
        script = materialize_hotspot_path_ps1()
    except Exception as exc:
        return False, f'Could not prepare Hotspot path: {exc}'
    from tools.diag_elevate import launch_ps1_elevated

    return launch_ps1_elevated(script, elevate=elevate, tool_label='Hotspot path')
