# ZubCut support diagnostic — collects logs for troubleshooting (any PC).
# Writes ZubCut-Support-Diag-*.txt and .json to the user's Desktop.
$ErrorActionPreference = 'Continue'

$Root = Split-Path -Parent $PSScriptRoot
$DiagPy = Join-Path $PSScriptRoot 'zubcut_support_diag.py'

function Find-Python {
    foreach ($cmd in @('py', 'python', 'python3')) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($exe) { return $cmd }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host 'Python not found. Install Python 3.11+ from python.org or run from a ZubCut dev checkout.' -ForegroundColor Red
    Write-Host 'Press Enter to close.'
    Read-Host | Out-Null
    exit 1
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host 'Re-launching as Administrator (recommended for full Npcap tests)...' -ForegroundColor Yellow
    $argList = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`""
    )
    foreach ($a in $args) { $argList += $a }
    Start-Process powershell -Verb RunAs -ArgumentList $argList
    exit
}

Write-Host '=== ZubCut Support Diagnostic ===' -ForegroundColor Cyan
Write-Host "Repo: $Root"
Write-Host ''

Set-Location $Root
$victimArgs = @()
foreach ($a in $args) {
    if ($a -match '^\d{1,3}(\.\d{1,3}){3}$') {
        $victimArgs += @('--victim-ip', $a)
    }
}

& $py $DiagPy @victimArgs
$code = $LASTEXITCODE

Write-Host ''
if ($code -eq 0) {
    Write-Host 'Done. Send the .txt and .json from your Desktop to ZubCut support.' -ForegroundColor Green
} else {
    Write-Host 'Done with issues — review the report and send both files to support.' -ForegroundColor Yellow
}
Write-Host 'Press Enter to close.'
Read-Host | Out-Null
exit $code
