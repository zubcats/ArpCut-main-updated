#Requires -Version 5.1
<#
.SYNOPSIS
  Allow ZubCut through Windows Defender before install or launch.

.DESCRIPTION
  Defender often quarantines unsigned PyInstaller + packet tools. Run this
  *before* setup — exclusion inside the installer never runs if setup is blocked.

  1. Adds a folder exclusion for C:\Program Files\ZubCut (creates it if missing)
  2. Adds a process exclusion for ZubCut.exe
  3. Optionally excludes Downloads so the setup .exe is not eaten
  4. Best-effort restore of quarantined ZubCut files

  Does not change third-party antivirus (Avast, Bitdefender, etc.).

.EXAMPLE
  Right-click Allow-ZubCut-Defender.bat -> Run as administrator
#>
[CmdletBinding()]
param(
    [switch]$SkipDownloads
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Add-ExclusionPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    try {
        Add-MpPreference -ExclusionPath $Path -ErrorAction Stop
        Write-Host "  exclusion: $Path" -ForegroundColor Green
    } catch {
        Write-Host "  FAILED exclusion $Path - $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

if (-not (Test-IsAdmin)) {
    Write-Host 'Run as Administrator: right-click Allow-ZubCut-Defender.bat' -ForegroundColor Red
    exit 1
}

$installDir = Join-Path ${env:ProgramFiles} 'ZubCut'
if (-not (Test-Path -LiteralPath $installDir)) {
    try {
        New-Item -ItemType Directory -Path $installDir -Force | Out-Null
        Write-Host "Created $installDir so Defender can exclude it." -ForegroundColor DarkGray
    } catch {
        Write-Host "Could not create $installDir - $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host 'Adding Windows Defender exclusions for ZubCut...' -ForegroundColor Cyan
Add-ExclusionPath $installDir
try {
    Add-MpPreference -ExclusionProcess 'ZubCut.exe' -ErrorAction Stop
    Write-Host '  process: ZubCut.exe' -ForegroundColor Green
} catch {
    Write-Host "  FAILED process exclusion - $($_.Exception.Message)" -ForegroundColor Yellow
}

if (-not $SkipDownloads) {
    $downloads = Join-Path $env:USERPROFILE 'Downloads'
    if (Test-Path -LiteralPath $downloads) {
        Add-ExclusionPath $downloads
    }
}

$mp = Join-Path ${env:ProgramFiles} 'Windows Defender\MpCmdRun.exe'
if (Test-Path -LiteralPath $mp) {
    Write-Host ''
    Write-Host 'Trying to restore quarantined ZubCut files...' -ForegroundColor Cyan
    try {
        $listed = & $mp -Restore -ListAll 2>&1 | Out-String
        if ($listed -match '(?i)ZubCut|python311\.dll|WinDivert') {
            foreach ($rel in @('ZubCut.exe', '_internal\python311.dll')) {
                $fp = Join-Path $installDir $rel
                & $mp -Restore -FilePath $fp 2>$null | Out-Null
            }
            Write-Host '  restore requested for ZubCut install files (if they were quarantined).' -ForegroundColor Green
        } else {
            Write-Host '  no ZubCut names in the quarantine list (ok if already deleted).' -ForegroundColor DarkGray
        }
    } catch {
        Write-Host "  restore skipped - $($_.Exception.Message)" -ForegroundColor DarkGray
    }
}

Write-Host ''
Write-Host 'Next:' -ForegroundColor Cyan
Write-Host '  1. Re-download ZubCut-Setup if Defender ate it.'
Write-Host '  2. Run the setup as Administrator.'
Write-Host '  3. Open ZubCut from the Start menu.'
Write-Host 'Leave these exclusions in place. This only covers Windows Defender.'
exit 0
