#Requires -Version 5.1
<#
.SYNOPSIS
  Wait for the Windows installer workflow for the current commit, then download
  and launch the experimental ZubCut installer.

  Lives in tools/ (committed) so CI-watch works on every clone. Logs to
  %TEMP%\zubcut-ci-watch.log and opens it in Notepad on failure.

.EXAMPLE
  cd <repo>
  .\tools\watch-experimental-ci-and-install.ps1
#>
param(
    [string]$Branch = 'experimental',
    [string]$WorkflowFile = 'build-windows-installer.yml',
    [switch]$Push,
    [int]$WaitForRunSeconds = 1200,
    [int]$PostSuccessSleepSeconds = 90,
    [int]$DownloadAttempts = 5,
    [int]$DownloadRetrySleepSeconds = 25
)

$ErrorActionPreference = 'Stop'

$installerUrl = 'https://github.com/zubcats/ZubCut/releases/download/experimental-latest/ZubCut-Setup-experimental.exe'
$repoRoot = Split-Path -Parent $PSScriptRoot
$LogFile = Join-Path $env:TEMP 'zubcut-ci-watch.log'

function Merge-FullMachinePath {
    # Child PowerShell from Start-Process often has a tiny PATH; restore Machine+User PATH.
    try {
        $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $u = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ($m) { $env:Path = $m + ';' + $env:Path }
        if ($u) { $env:Path = $u + ';' + $env:Path }
    } catch {}
}

function Log([string]$msg) {
    $line = "$(Get-Date -Format o) $msg"
    try {
        Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    } catch {}
    Write-Host $line
}

function Fail([string]$msg) {
    Log "ERROR: $msg"
    try {
        Start-Process notepad.exe -ArgumentList $LogFile
    } catch {}
    throw $msg
}

Merge-FullMachinePath
Set-Location $repoRoot
Log "=== watch-experimental-ci-and-install start (repo=$repoRoot) ==="

function Assert-Gh {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Fail 'GitHub CLI (gh) not found on PATH. Install https://cli.github.com/ and run: gh auth login'
    }
}

function Assert-Git {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Fail 'git not found on PATH. Install Git for Windows or fix PATH.'
    }
}

function Get-HeadSha {
    Assert-Git
    $sha = (git -C $repoRoot rev-parse HEAD 2>$null)
    if (-not $sha) { Fail 'Could not read git HEAD (not a repo?).' }
    return $sha.Trim()
}

Assert-Gh

if ($Push) {
    Log ">> git push origin $Branch"
    git -C $repoRoot push origin $Branch
    if ($LASTEXITCODE -ne 0) { Fail "git push failed ($LASTEXITCODE)" }
}

$sha = Get-HeadSha
Log ">> Waiting for workflow run (commit=$sha branch=$Branch workflow=$WorkflowFile)"

function Find-RunIdForSha([string]$wantSha) {
    # gh uses the git repo in the current directory (must be $repoRoot).
    $json = gh run list --workflow $WorkflowFile --branch $Branch --commit $wantSha --limit 1 --json databaseId,status,conclusion 2>$null
    if ($LASTEXITCODE -eq 0 -and $json -and $json -ne '[]') {
        $run = $json | ConvertFrom-Json
        if ($run.databaseId) { return [string]$run.databaseId }
    }
    $json2 = gh run list --workflow $WorkflowFile --branch $Branch --limit 25 --json databaseId,headSha,status,conclusion 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $json2) { return $null }
    foreach ($r in @($json2 | ConvertFrom-Json)) {
        if ($r.headSha -eq $wantSha -and $r.databaseId) { return [string]$r.databaseId }
    }
    return $null
}

$deadline = (Get-Date).AddSeconds($WaitForRunSeconds)
$runId = $null
while ((Get-Date) -lt $deadline) {
    $runId = Find-RunIdForSha $sha
    if ($runId) {
        Log ">> Found run id=$runId"
        break
    }
    Start-Sleep -Seconds 5
}

if (-not $runId) {
    Fail "No GitHub Actions run for this commit within ${WaitForRunSeconds}s (push $Branch and ensure workflow exists)."
}

Log '>> gh run watch (waiting for job to finish)...'
gh run watch $runId --exit-status
if ($LASTEXITCODE -ne 0) {
    Fail "Workflow run $runId failed or was cancelled (exit $LASTEXITCODE)."
}

Log ">> Sleeping ${PostSuccessSleepSeconds}s for release asset..."
Start-Sleep -Seconds $PostSuccessSleepSeconds

$out = Join-Path $env:TEMP 'ZubCut-Setup-experimental-download.exe'
$minBytes = 512000

for ($a = 1; $a -le $DownloadAttempts; $a++) {
    Log ">> Download attempt $a / $DownloadAttempts"
    try {
        Invoke-WebRequest -Uri $installerUrl -OutFile $out -UseBasicParsing
    } catch {
        Log "Download error: $_"
    }
    if ((Test-Path $out) -and ((Get-Item $out).Length -ge $minBytes)) {
        Log ">> Download OK ($((Get-Item $out).Length) bytes)"
        break
    }
    if ($a -lt $DownloadAttempts) {
        Start-Sleep -Seconds $DownloadRetrySleepSeconds
    }
}

if (-not (Test-Path $out) -or ((Get-Item $out).Length -lt $minBytes)) {
    Fail "Installer download failed after $DownloadAttempts attempts (expected at least $minBytes bytes)."
}

Log ">> Launching installer: $out"
Start-Process -FilePath $out
Log '=== Done (installer started). Complete the wizard to update ZubCut. ==='
