# Start ZubLock (elevated). Called by the desktop shortcut.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Show-Msg([string]$Text) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($Text, 'ZubLock') | Out-Null
}

if (-not (Test-Admin)) {
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', "`"$PSCommandPath`""
    )
    exit 0
}

function Get-PythonW {
    $dirs = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310')
    )
    foreach ($dir in $dirs) {
        $w = Join-Path $dir 'pythonw.exe'
        $py = Join-Path $dir 'python.exe'
        if ((Test-Path -LiteralPath $w) -and (Test-Path -LiteralPath $py)) {
            try {
                & $py -c 'import tkinter' 2>$null
                if ($LASTEXITCODE -eq 0) { return $w }
            } catch {}
        }
    }
    $cmd = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $exe = & py -3 -c 'import tkinter, sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) {
                $w = ([string]$exe).Trim() -replace 'python\.exe$', 'pythonw.exe'
                if (Test-Path -LiteralPath $w) { return $w }
            }
        } catch {}
    }
    return $null
}

$gui = Join-Path $Root 'zublock_gui.py'
if (-not (Test-Path -LiteralPath $gui)) {
    Show-Msg 'ZubLock files are missing. Run Install-ZubLock.cmd.'
    exit 1
}
$pythonw = Get-PythonW
if (-not $pythonw) {
    Show-Msg 'Python with Tk was not found. Run Install-ZubLock.cmd.'
    exit 1
}

Start-Process -FilePath $pythonw -ArgumentList "`"$gui`"" -WorkingDirectory $Root
