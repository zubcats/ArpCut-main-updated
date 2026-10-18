# Install ZubLock for the current user. Downloads WinDivert and Python+Tk if needed.
# Standalone - not part of ZubCut.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Src = $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'files\zublock_gui.py')) {
    $Src = Join-Path $PSScriptRoot 'files'
}
$Dest = Join-Path $env:LOCALAPPDATA 'ZubLock'
$PyVer = '3.11.9'
$PyUrl = "https://www.python.org/ftp/python/$PyVer/python-$PyVer-amd64.exe"
$WdVer = '2.2.2'
$WdUrl = "https://github.com/basil00/WinDivert/releases/download/v$WdVer/WinDivert-$WdVer-A.zip"

if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'ZubLock needs 64-bit Windows.'
}

$Runtime = @(
    'zublock_gui.py',
    'zublock_engine.py',
    'zublock_rules.py',
    'lock_ranges.txt',
    'zublock.ico',
    'Launch-ZubLock.ps1',
    'Launch-ZubLock.cmd',
    'Launch-ZubLock.vbs',
    'Install-ZubLock.ps1',
    'Install-ZubLock.cmd',
    'README.md'
)

function Write-Step([string]$Message) {
    Write-Host $Message
}

function Get-TkPython {
    $dirs = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310'),
        (Join-Path ${env:ProgramFiles} 'Python311'),
        (Join-Path ${env:ProgramFiles} 'Python312')
    )
    foreach ($dir in $dirs) {
        $exe = Join-Path $dir 'python.exe'
        if (Test-Path -LiteralPath $exe) {
            try {
                & $exe -c 'import tkinter' 2>$null
                if ($LASTEXITCODE -eq 0) { return $exe }
            } catch {}
        }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $exe = & py -3 -c 'import tkinter, sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return ([string]$exe).Trim() }
        } catch {}
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            & $cmd.Source -c 'import tkinter' 2>$null
            if ($LASTEXITCODE -eq 0) { return $cmd.Source }
        } catch {}
    }
    return $null
}

function Install-PythonTk {
    $existing = Get-TkPython
    if ($existing) {
        Write-Step "Python+Tk: $existing"
        return $existing
    }
    Write-Step "Downloading Python $PyVer (Tcl/Tk)..."
    $tmp = Join-Path $env:TEMP "python-$PyVer-zublock.exe"
    Invoke-WebRequest -Uri $PyUrl -OutFile $tmp -UseBasicParsing
    $args = @(
        '/quiet',
        'InstallAllUsers=0',
        'PrependPath=1',
        'Include_tcltk=1',
        'Include_pip=0',
        'Include_doc=0',
        'Include_test=0',
        'Include_launcher=1',
        'Shortcuts=0'
    )
    $proc = Start-Process -FilePath $tmp -ArgumentList $args -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Python installer exited $($proc.ExitCode)"
    }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path', 'User')
    $got = Get-TkPython
    if (-not $got) {
        throw 'Python installed but Tk is still missing. Re-run Install-ZubLock.cmd.'
    }
    Write-Step "Python+Tk: $got"
    return $got
}

function Copy-WinDivertFrom([string]$FromDir, [string]$ToDir) {
    $dll = Join-Path $FromDir 'WinDivert.dll'
    $sys = Join-Path $FromDir 'WinDivert64.sys'
    if (-not ((Test-Path -LiteralPath $dll) -and (Test-Path -LiteralPath $sys))) {
        return $false
    }
    New-Item -ItemType Directory -Path $ToDir -Force | Out-Null
    foreach ($name in @('WinDivert.dll', 'WinDivert64.sys', 'WinDivert-LICENSE.txt')) {
        $from = Join-Path $FromDir $name
        if (Test-Path -LiteralPath $from) {
            Copy-Item -LiteralPath $from -Destination (Join-Path $ToDir $name) -Force
            Unblock-File -LiteralPath (Join-Path $ToDir $name) -ErrorAction SilentlyContinue
        }
    }
    return $true
}

function Install-WinDivert {
    $wd = Join-Path $Dest 'windivert'
    $dll = Join-Path $wd 'WinDivert.dll'
    $sys = Join-Path $wd 'WinDivert64.sys'
    if ((Test-Path -LiteralPath $dll) -and (Test-Path -LiteralPath $sys)) {
        Write-Step "WinDivert already in $wd"
        return
    }
    $repoRoot = Split-Path $Src -Parent
    $localCopies = @(
        (Join-Path $repoRoot 'windivert'),
        (Join-Path $repoRoot 'installer\windivert'),
        (Join-Path $env:LOCALAPPDATA 'ZubCut\windivert'),
        (Join-Path ${env:ProgramFiles} 'ZubCut\windivert')
    )
    foreach ($dir in $localCopies) {
        if (Copy-WinDivertFrom $dir $wd) {
            Write-Step "WinDivert copied from $dir"
            return
        }
    }
    Write-Step "Downloading WinDivert $WdVer..."
    $stage = Join-Path $env:TEMP ('zublock-wd-' + [guid]::NewGuid().ToString('n'))
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    try {
        $zip = Join-Path $stage 'WinDivert.zip'
        Invoke-WebRequest -Uri $WdUrl -OutFile $zip -UseBasicParsing
        Unblock-File -LiteralPath $zip -ErrorAction SilentlyContinue
        $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
        if (Test-Path -LiteralPath $tar) {
            & $tar -xf $zip -C $stage
        } else {
            Expand-Archive -Path $zip -DestinationPath $stage -Force
        }
        $x64 = Get-ChildItem -Path $stage -Recurse -Directory -Filter 'x64' |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'WinDivert.dll') } |
            Select-Object -First 1
        if (-not $x64) {
            throw 'Windows blocked WinDivert. Allow WinDivert in Windows Security, then run Install-ZubLock.cmd again.'
        }
        if (-not (Copy-WinDivertFrom $x64.FullName $wd)) {
            throw 'Windows blocked WinDivert. Allow WinDivert in Windows Security, then run Install-ZubLock.cmd again.'
        }
        $lic = Get-ChildItem -Path $stage -Recurse -File -Filter 'LICENSE' | Select-Object -First 1
        if ($lic) {
            Copy-Item -LiteralPath $lic.FullName -Destination (Join-Path $wd 'WinDivert-LICENSE.txt') -Force
        }
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Step "WinDivert copied to $wd"
}

function Install-Files {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    foreach ($name in $Runtime) {
        $from = Join-Path $Src $name
        if ($name -eq 'zublock.ico' -and -not (Test-Path -LiteralPath $from)) {
            $repoIco = Join-Path (Split-Path $Src -Parent) 'exe\zubcut_shell.ico'
            if (Test-Path -LiteralPath $repoIco) { $from = $repoIco }
        }
        if (-not (Test-Path -LiteralPath $from)) {
            if ($name -eq 'README.md') { continue }
            throw "Missing $name - unzip the whole ZubLock folder."
        }
        $to = Join-Path $Dest $name
        $fromFull = [IO.Path]::GetFullPath($from)
        $toFull = [IO.Path]::GetFullPath($to)
        if ($fromFull -eq $toFull) { continue }
        Copy-Item -LiteralPath $from -Destination $to -Force
    }
    Write-Step "Files copied to $Dest"
}

function Install-Shortcut {
    $w = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath('Desktop')
    $lnkPath = Join-Path $desktop 'ZubLock.lnk'
    $ico = Join-Path $Dest 'zublock.ico'
    $vbs = Join-Path $Dest 'Launch-ZubLock.vbs'
    $lnk = $w.CreateShortcut($lnkPath)
    $lnk.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
    $lnk.Arguments = '"' + $vbs + '"'
    $lnk.WorkingDirectory = $Dest
    $lnk.WindowStyle = 7
    $lnk.Description = 'ZubLock'
    if (Test-Path -LiteralPath $ico) {
        $lnk.IconLocation = "$ico,0"
    }
    $lnk.Save()
    $startDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    New-Item -ItemType Directory -Path $startDir -Force | Out-Null
    Copy-Item -LiteralPath $lnkPath -Destination (Join-Path $startDir 'ZubLock.lnk') -Force
    Write-Step "Desktop shortcut: $lnkPath"
}

Install-Files
Install-WinDivert
Install-PythonTk | Out-Null
Install-Shortcut
Write-Host ''
Write-Host 'ZubLock is on your desktop. Open it, approve UAC, then use Lock ON / Lock OFF.'
Write-Host 'Keep the window open while locked. Console goes on this PC hotspot.'
