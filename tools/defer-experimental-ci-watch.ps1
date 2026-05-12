#Requires -Version 5.1
<#
  Wait (default 6 minutes) then run tools/watch-experimental-ci-and-install.ps1.

  Start from repo root (no visible window), e.g.:
    Start-Process powershell.exe -WindowStyle Hidden -WorkingDirectory $pwd `
      -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',(Resolve-Path '.\tools\defer-experimental-ci-watch.ps1')

  Log: %TEMP%\zubcut-ci-watch.log
#>
param(
    [int]$DelaySeconds = 360
)

$ErrorActionPreference = 'Stop'

# Hide this console when launched visibly (e.g. Start-Process without -WindowStyle Hidden).
if ($Host.Name -eq 'ConsoleHost') {
    try {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class ZubcutDeferConsole {
  [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  public static void Hide() {
    var h = GetConsoleWindow();
    if (h != System.IntPtr.Zero) ShowWindow(h, 0);
  }
}
'@
    } catch {
        # Type may already exist in this session
    }
    try {
        [ZubcutDeferConsole]::Hide()
    } catch {}
}

try {
    $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $u = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($m) { $env:Path = $m + ';' + $env:Path }
    if ($u) { $env:Path = $u + ';' + $env:Path }
} catch {}

$repoRoot = Split-Path -Parent $PSScriptRoot
$watch = Join-Path $repoRoot 'tools\watch-experimental-ci-and-install.ps1'

if (-not (Test-Path -LiteralPath $watch)) {
    throw "Missing committed script: $watch"
}

$logFile = Join-Path $env:TEMP 'zubcut-ci-watch.log'
try {
    $line = "$(Get-Date -Format o) defer: sleeping ${DelaySeconds}s then $watch"
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
} catch {}

Start-Sleep -Seconds $DelaySeconds
Set-Location $repoRoot
& $watch
