# ZubCut Quick Network Diagnostic (no Python / no repo required)
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
$gateways = [regex]::Matches($ipcfg, 'Default Gateway[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})') |
    ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique

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
