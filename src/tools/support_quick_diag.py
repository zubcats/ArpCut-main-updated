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
# Writes ZubCut-Quick-Diag-*.txt on the Desktop for screenshots.

$ErrorActionPreference = 'SilentlyContinue'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$desktop = [Environment]::GetFolderPath('Desktop')
$out = Join-Path $desktop "ZubCut-Quick-Diag-$stamp.txt"

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

$admin = Test-IsAdmin
$npcapPath = 'C:\Windows\SysWOW64\Npcap'
$npcapOk = Test-Path $npcapPath
$winpcapKey = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst'
if (-not $winpcapKey) {
    $winpcapKey = Test-Path 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst'
}
$winpcapApps = @(Has-UninstallDisplay 'WinPcap|Win10Pcap')
$npcapApps = @(Has-UninstallDisplay 'Npcap')
$nmapApps = @(Has-UninstallDisplay 'Nmap')

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
$has137 = $ipcfg -match '192\.168\.137\.'
# Match English + common localized labels (FR: Passerelle par défaut, DE: Standardgateway, …).
$gateways = [regex]::Matches(
    $ipcfg,
    '(?i)(?:Default Gateway|Passerelle par d[eé]faut|Standardgateway|Puerta de enlace predeterminada|Gateway predefinito)[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})'
) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
# Fallback: any IPv4 on a gateway-ish line (covers odd locales / spacing).
if (-not $gateways) {
    $gateways = [regex]::Matches(
        $ipcfg,
        '(?i)(?:gateway|passerelle|gateway)[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})'
    ) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
}
# Prefer Get-NetRoute when available (locale-independent).
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

$lines = @()
$lines += '========================================================================'
$lines += ' ZubCut Quick Network Diagnostic (PowerShell)'
$lines += '========================================================================'
$lines += ("Generated: {0}" -f (Get-Date).ToString('u'))
$lines += ("Administrator: {0}" -f $(if ($admin) { 'yes' } else { 'NO — right-click PowerShell -> Run as administrator' }))
$lines += ''
$lines += '>>> SCREENSHOT THIS SUMMARY <<<'
$lines += '------------------------------------------------------------------------'
$lines += ("[{0}] Running as Administrator" -f $(if ($admin) { 'PASS' } else { 'FAIL' }))
$lines += ("[{0}] Npcap folder present ({1})" -f $(if ($npcapOk) { 'PASS' } else { 'FAIL' }), $npcapPath)
$lines += ("[{0}] WinPcap uninstall key absent" -f $(if ($winpcapKey) { 'FAIL' } else { 'PASS' }))
$lines += ("[{0}] WinPcap/Win10Pcap not in Apps list" -f $(if ($winpcapApps.Count) { 'FAIL' } else { 'PASS' }))
$lines += ("[{0}] Hotspot 192.168.137.x visible" -f $(if ($has137) { 'PASS' } else { 'WARN' }))
$lines += ("[{0}] WinDivert bundle under ZubCut" -f $(if ($wdOk) { 'PASS' } else { 'WARN' }))
$lines += ("[INFO] Default gateways: {0}" -f ($(if ($gateways) { $gateways -join ', ' } else { '(none)' })))
$lines += ("[INFO] Clumsy mode (settings): {0}" -f ($(if ($null -eq $clumsy) { '(unknown)' } else { $clumsy })))
$lines += ("[INFO] Saved adapter (settings): {0}" -f ($(if ($ifaceSaved) { $ifaceSaved } else { '(not set)' })))
$lines += '------------------------------------------------------------------------'
$lines += ''
$lines += '--- Related programs ---'
foreach ($n in ($npcapApps + $winpcapApps + $nmapApps | Select-Object -Unique)) { $lines += "  $n" }
if (-not ($npcapApps + $winpcapApps + $nmapApps)) { $lines += '  (none matched)' }
$lines += ''
$lines += '--- IPv4 adapters ---'
foreach ($a in $adapters) {
    $lines += ("  {0}: {1}" -f $a.InterfaceAlias, $a.IPAddress)
}
$lines += ''
$lines += '--- WinDivert paths ---'
if (-not $wdBundles.Count) { $lines += '  (no ZubCut install folder found)' }
foreach ($b in $wdBundles) {
    $lines += ("  {0}  dll={1} sys={2} complete={3}" -f $b.Dir, $b.Dll, $b.Sys, $b.Complete)
}
$lines += ''
$lines += '--- ARP sample (first 40 lines) ---'
$arp = arp -a | Select-Object -First 40
foreach ($l in $arp) { $lines += "  $l" }
$lines += ''
$lines += '--- Recommended next steps ---'
if (-not $admin) { $lines += '  1. Re-run this script as Administrator.' }
if (-not $npcapOk) { $lines += '  2. Install Npcap from https://npcap.com/ (enable Wi-Fi adapter).' }
if ($winpcapKey -or $winpcapApps.Count) {
    $lines += '  3. Uninstall WinPcap/Win10Pcap, reboot, keep Npcap only.'
}
if ($clumsy -and -not $has137) {
    $lines += '  4. Clumsy ON but no 192.168.137.x — turn Mobile Hotspot ON, wait, put PS5 on hotspot, rescan.'
}
if ($clumsy -and -not $wdOk) {
    $lines += '  5. Reinstall ZubCut with "Clumsy mode" checked (WinDivert missing).'
}
if ($gateways.Count -gt 1) {
    $lines += '  6. Multiple gateways (modem+router?) — pick the LAN router adapter in ZubCut Settings.'
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
    """Write the diagnostic script under %TEMP%\\ZubCut for elevated PowerShell."""
    text = quick_diag_ps1_text()
    if not text.strip().endswith('\n'):
        text = text.rstrip('\r\n') + '\n'
    dest_dir = Path(tempfile.gettempdir()) / 'ZubCut'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / QUICK_DIAG_PS1_NAME
    dest.write_text(text, encoding='utf-8', newline='\n')
    return dest


def _powershell_exe() -> str:
    system_root = os.environ.get('SystemRoot') or os.environ.get('WINDIR') or r'C:\Windows'
    candidate = os.path.join(
        system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'
    )
    if os.path.isfile(candidate):
        return candidate
    return 'powershell.exe'


def launch_quick_network_diag_elevated(*, elevate=None) -> tuple[bool, str]:
    """
    Open Admin PowerShell, run the quick network diagnostic, open the Desktop report.

    Returns ``(ok, status_message)`` for the Logs window status strip.
    ``elevate`` is injectable for tests (defaults to ``spawn_windows_elevated``).
    """
    if not sys.platform.startswith('win'):
        return False, 'General checks are Windows-only.'
    try:
        script = materialize_quick_diag_ps1()
    except Exception as exc:
        return False, f'Could not prepare general checks: {exc}'

    # Quote path for ShellExecute params (spaces / specials).
    script_s = str(script)
    params = (
        '-NoProfile -ExecutionPolicy Bypass -File '
        + '"'
        + script_s.replace('"', '')
        + '"'
    )
    try:
        if elevate is None:
            from tools.utils_gui import spawn_windows_elevated as elevate
        ok = bool(elevate(_powershell_exe(), params))
    except Exception as exc:
        return False, f'Could not start Admin PowerShell: {exc}'
    if not ok:
        return (
            False,
            'General checks cancelled or failed to elevate — approve the UAC prompt.',
        )
    return (
        True,
        'General checks started in Admin PowerShell — '
        'screenshot the SUMMARY in Notepad (Desktop ZubCut-Quick-Diag-*.txt) and send it to support.',
    )
