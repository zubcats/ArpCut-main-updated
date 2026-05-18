# Remove leftover ZubCut Kill/Dupe/Lag blocks that can break PS5 hotspot internet.
# Run with ZubCut CLOSED for a full clean (otherwise in-memory gates may return).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_clear_stale_attacks_log.txt'
function L($m) { Write-Host $m; Add-Content $log $m -Encoding utf8 -ErrorAction SilentlyContinue }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    L 'Administrator required — click Yes on UAC'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

'' | Set-Content $log -Force
L "=== Clear stale ZubCut attacks $(Get-Date -Format o) ==="

$zub = Get-Process -Name 'ZubCut' -ErrorAction SilentlyContinue
if ($zub) {
    L 'WARN: ZubCut is running — close it first, then run this again for a complete clean.'
} else {
    L 'ZubCut not running (good)'
}

# PS5 / hotspot clients on 192.168.137.x
L '--- Hotspot ARP ---'
$ps5Ips = @()
arp -a | Select-String '192\.168\.137\.\d+' | ForEach-Object {
    if ($_.Line -match '\b(192\.168\.137\.\d+)\b' -and $Matches[1] -notmatch '\.(1|255)$') {
        L "  $($Matches[1])"
        $ps5Ips += $Matches[1]
    }
}
if ($ps5Ips.Count -eq 0) {
    L '  (no 192.168.137.x client — connect PS5 to osps first if you want that IP cleared)'
}

# Python teardown (same logic as app exit / Clear attacks)
$pyCandidates = @()
foreach ($cmdName in @('python', 'py')) {
    $c = Get-Command $cmdName -ErrorAction SilentlyContinue
    if ($c) { $pyCandidates += $c.Source }
}
$pyCandidates += @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
)
$py = $pyCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

$script = Join-Path $PSScriptRoot 'clear_stale_zubcut_attacks.py'
function Remove-ZubCutAttackFirewallRules {
    $n = 0
    $rulesOut = netsh advfirewall firewall show rule name=all verbose 2>$null | Out-String
    foreach ($line in ($rulesOut -split "`r?`n")) {
        if ($line -notmatch '^\s*Rule Name:\s+(zubcut.+)') { continue }
        $name = $Matches[1].Trim()
        $nl = $name.ToLowerInvariant()
        $isAttack = ($nl -match '^zubcut_(ip_|block_|port_)') -or ($nl -match '_to_')
        if (-not $isAttack) { continue }
        netsh advfirewall firewall delete rule name="$name" 2>$null | Out-Null
        L "  Removed $name"
        $n++
    }
    return $n
}

function Stop-ZubCutWinDivertService {
    foreach ($args in @('stop WinDivert', 'delete WinDivert')) {
        $null = & sc.exe $args.Split(' ') 2>&1
    }
    L 'WinDivert service: stopped/removed (if present)'
}

$pyOk = $false
if ($py -and (Test-Path $script)) {
    L ''
    L 'Running ZubCut attack teardown (Python)...'
    try {
        $proc = Start-Process -FilePath $py -ArgumentList @($script) -Wait -PassThru -NoNewWindow -RedirectStandardOutput (Join-Path $env:TEMP 'zubcut_clear_out.txt') -RedirectStandardError (Join-Path $env:TEMP 'zubcut_clear_err.txt')
        Get-Content (Join-Path $env:TEMP 'zubcut_clear_out.txt') -ErrorAction SilentlyContinue | ForEach-Object { L $_ }
        Get-Content (Join-Path $env:TEMP 'zubcut_clear_err.txt') -ErrorAction SilentlyContinue | ForEach-Object { if ($_ -and $_ -notmatch 'Python was not found') { L "  $_" } }
        $pyOk = ($proc.ExitCode -eq 0)
    } catch {
        L "  Python failed: $($_.Exception.Message)"
    }
}
if (-not $pyOk) {
    L 'Purging attack firewall rules via netsh...'
    $n = Remove-ZubCutAttackFirewallRules
    L "Removed $n attack rule(s)"
    Stop-ZubCutWinDivertService
}

# Any firewall BLOCK still targeting hotspot subnet?
L ''
L '--- Block rules on 192.168.137.0/24 (should be none) ---'
$bad = 0
$rulesOut = netsh advfirewall firewall show rule name=all verbose 2>$null | Out-String
$chunks = $rulesOut -split '(?=^\s*Rule Name:)' -split "`r?`n"
$current = ''
foreach ($line in ($rulesOut -split "`r?`n")) {
    if ($line -match '^\s*Rule Name:\s+(.+)$') { $current = $Matches[1].Trim(); continue }
    if ($current -and $line -match '192\.168\.137' -and $line -match 'Action:\s*Block') {
        L "  BLOCK: $current"
        $bad++
    }
}
if ($bad -eq 0) { L '  (none)' }

L ''
L 'Done. Reconnect PS5 to osps and test internet (ZubCut Kill/Dupe OFF).'
L 'Log: ' + $log
