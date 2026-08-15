#Requires -Version 5.1
<#
.SYNOPSIS
  Fully remove ZubCut from this PC (install, shortcuts, autostart, stray EXEs, user data).

.DESCRIPTION
  Use when an old ZubCut keeps launching (Settings shows "Updates Disabled") even after
  installing a newer setup. This script:

    1. Stops running ZubCut processes
    2. Runs any Inno Setup uninstallers (silent)
    3. Deletes Program Files / leftover install folders
    4. Removes Start Menu / Desktop / Startup shortcuts
    5. Clears Run / AppCompatFlags registry entries
    6. Searches common folders for stray ZubCut.exe copies
    7. Removes most of %APPDATA%\ZubCut and %LOCALAPPDATA%\ZubCut (unless -KeepUserData)
       Control Panel account files are PRESERVED by default (see -WipeControlPanelData)
    8. Clears updater temp leftovers

  Does NOT uninstall Npcap / WinDivert system drivers.

.PARAMETER KeepUserData
  Keep %APPDATA%\ZubCut (settings, license). Still removes binaries and shortcuts.

.PARAMETER WipeControlPanelData
  Also delete Control Panel secrets under %APPDATA%\ZubCut:
  paid-license-admin.json, paid-license-signing.key, license-manager-cloud-sync.json.
  Default is to KEEP these so a ZubCut client wipe does not empty the Accounts tab.

.PARAMETER AlsoControlPanel
  Also remove ZubCut Control Panel / License Manager installs (the program).
  Does NOT wipe account data unless -WipeControlPanelData is also set.

.PARAMETER WhatIf
  Print actions without deleting.

.EXAMPLE
  Right-click Uninstall-ZubCut-Completely.bat -> Run as administrator
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$KeepUserData,
    [switch]$WipeControlPanelData,
    [switch]$AlsoControlPanel
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Done([string]$Message) {
    Write-Host "    $Message" -ForegroundColor DarkGray
}

function Remove-PathSafe([string]$Path, [string]$Why = '') {
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $label = if ($Why) { "$Path ($Why)" } else { $Path }
    if ($PSCmdlet.ShouldProcess($label, 'Remove')) {
        try {
            if (Test-Path -LiteralPath $Path -PathType Container) {
                Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            } else {
                Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
            }
            Write-Host "  removed: $Path" -ForegroundColor Green
            $script:RemovedCount++
        } catch {
            Write-Host "  FAILED: $Path - $($_.Exception.Message)" -ForegroundColor Yellow
            $script:FailedCount++
        }
    }
}

function Stop-ZubCutProcesses {
    Write-Step 'Stopping ZubCut processes'
    $names = @('ZubCut', 'ZubCut.exe')
    if ($AlsoControlPanel) {
        $names += @('ZubCutControlPanel', 'ZubCutControlPanel.exe', 'ZubCutLicenseManager', 'ZubCut-License-Manager')
    }
    $procs = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $n = $_.ProcessName
            ($names -contains $n) -or ($n -like 'ZubCut*')
        })
    if (-not $procs) {
        Write-Done 'No ZubCut processes running.'
        return
    }
    foreach ($p in $procs) {
        $path = ''
        try { $path = $p.Path } catch { }
        Write-Host "  stopping PID $($p.Id) $($p.ProcessName) $path" -ForegroundColor Yellow
        if ($PSCmdlet.ShouldProcess("PID $($p.Id)", 'Stop-Process')) {
            try {
                Stop-Process -Id $p.Id -Force -ErrorAction Stop
                $script:RemovedCount++
            } catch {
                Write-Host "  FAILED to stop PID $($p.Id): $($_.Exception.Message)" -ForegroundColor Yellow
                $script:FailedCount++
            }
        }
    }
    Start-Sleep -Seconds 1
}

function Get-UninstallEntries {
    $roots = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKCU:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    $wantedAppIds = @(
        '{E4B9F5C2-8D3A-4F1E-9C7B-2A6D8E0F1A3C}_is1'   # ZubCut
    )
    if ($AlsoControlPanel) {
        $wantedAppIds += @(
            '{A8E2C41B-5D93-4F7A-9B12-3C6D8E0F2A94}_is1',  # Control Panel
            '{3C91A74A-9F49-4A66-B3A6-6F353DF32E11}_is1'   # Legacy License Manager
        )
    }

    $hits = @()
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue | ForEach-Object {
            $keyPath = $_.PSPath
            $props = Get-ItemProperty -LiteralPath $keyPath -ErrorAction SilentlyContinue
            if (-not $props) { return }
            $name = [string]$props.DisplayName
            $keyLeaf = Split-Path -Leaf $_.Name
            $matchId = $wantedAppIds -contains $keyLeaf
            $matchName = $false
            if ($name) {
                $isControlPanel = ($name -match '(?i)(Control Panel|License Manager)')
                if ($isControlPanel) {
                    if ($AlsoControlPanel) { $matchName = $true }
                } elseif ($name -match '(?i)^ZubCut(\s|$)|(?i)^ZubCut Setup') {
                    $matchName = $true
                }
            }
            if (-not ($matchId -or $matchName)) { return }
            if (-not $AlsoControlPanel -and ($keyLeaf -match 'A8E2C41B|3C91A74A')) { return }

            $hits += [pscustomobject]@{
                DisplayName     = $name
                UninstallString = [string]$props.UninstallString
                QuietUninstall  = [string]$props.QuietUninstallString
                InstallLocation = [string]$props.InstallLocation
                KeyPath         = $keyPath
                KeyLeaf         = $keyLeaf
            }
        }
    }
    return $hits | Sort-Object DisplayName, KeyLeaf -Unique
}

function Invoke-InnoUninstall([string]$UninstallString) {
    if ([string]::IsNullOrWhiteSpace($UninstallString)) { return $false }
    $exe = $null
    $args = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
    $s = $UninstallString.Trim()
    if ($s.StartsWith('"')) {
        $end = $s.IndexOf('"', 1)
        if ($end -gt 1) {
            $exe = $s.Substring(1, $end - 1)
            $rest = $s.Substring($end + 1).Trim()
            if ($rest) { $args = "$rest $args" }
        } else {
            $exe = $s.Trim('"')
        }
    } elseif ($s -match '^(\S+)\s+(.*)$') {
        $exe = $Matches[1]
        $rest = $Matches[2].Trim()
        if ($rest) { $args = "$rest $args" }
    } else {
        $exe = $s
    }
    if (-not (Test-Path -LiteralPath $exe)) {
        Write-Host "  uninstaller missing: $exe" -ForegroundColor DarkYellow
        return $false
    }
    if ($PSCmdlet.ShouldProcess("$exe $args", 'Run uninstaller')) {
        Write-Host "  running: $exe $args" -ForegroundColor Yellow
        try {
            $p = Start-Process -FilePath $exe -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
            Write-Done "uninstaller exit code $($p.ExitCode)"
            return $true
        } catch {
            Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Yellow
            $script:FailedCount++
            return $false
        }
    }
    return $false
}

function Remove-InstallFolders {
    Write-Step 'Removing install folders'
    $dirs = @(
        (Join-Path ${env:ProgramFiles} 'ZubCut'),
        (Join-Path ${env:ProgramFiles(x86)} 'ZubCut'),
        (Join-Path $env:LOCALAPPDATA 'Programs\ZubCut')
    )
    if ($AlsoControlPanel) {
        $dirs += @(
            (Join-Path ${env:ProgramFiles} 'ZubCutControlPanel'),
            (Join-Path ${env:ProgramFiles(x86)} 'ZubCutControlPanel'),
            (Join-Path ${env:ProgramFiles} 'ZubCut License Manager'),
            (Join-Path ${env:ProgramFiles(x86)} 'ZubCut License Manager')
        )
    }
    foreach ($d in $dirs) {
        if ($d) { Remove-PathSafe $d 'install folder' }
    }
}

function Remove-ShortcutsAndStartup {
    Write-Step 'Removing shortcuts and Startup entries'
    $bases = @(
        [Environment]::GetFolderPath('Desktop'),
        [Environment]::GetFolderPath('CommonDesktopDirectory'),
        [Environment]::GetFolderPath('StartMenu'),
        [Environment]::GetFolderPath('CommonStartMenu'),
        [Environment]::GetFolderPath('Startup'),
        [Environment]::GetFolderPath('CommonStartup')
    ) | Where-Object { $_ }

    $patterns = @('ZubCut*.lnk', 'ZubCut*.url')
    if (-not $AlsoControlPanel) {
        # Still remove main-app shortcuts; Control Panel links often contain "Control Panel"
    }

    foreach ($base in $bases) {
        if (-not (Test-Path -LiteralPath $base)) { continue }
        foreach ($pat in $patterns) {
            Get-ChildItem -LiteralPath $base -Filter $pat -Recurse -Force -ErrorAction SilentlyContinue |
                Where-Object {
                    if ($AlsoControlPanel) { return $true }
                    # Keep Control Panel shortcuts unless requested
                    $_.Name -notmatch '(?i)Control Panel|License Manager'
                } |
                ForEach-Object { Remove-PathSafe $_.FullName 'shortcut' }
        }
        # Inno Start Menu group folders
        Get-ChildItem -LiteralPath $base -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -eq 'ZubCut' -or
                ($AlsoControlPanel -and $_.Name -match '(?i)^ZubCut')
            } |
            ForEach-Object { Remove-PathSafe $_.FullName 'Start Menu group' }
    }
}

function Remove-RegistryLaunchEntries {
    Write-Step 'Clearing autostart / AppCompatFlags registry'
    $runKeys = @(
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
        'HKCU:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'
    )
    $runNames = @('ZubCut')
    if ($AlsoControlPanel) {
        $runNames += @('ZubCutControlPanel', 'ZubCut Control Panel', 'ZubCutLicenseManager')
    }
    foreach ($rk in $runKeys) {
        if (-not (Test-Path -LiteralPath $rk)) { continue }
        foreach ($vn in $runNames) {
            $props = Get-ItemProperty -LiteralPath $rk -ErrorAction SilentlyContinue
            if ($props -and ($props.PSObject.Properties.Name -contains $vn)) {
                if ($PSCmdlet.ShouldProcess("$rk\$vn", 'Remove Run value')) {
                    try {
                        Remove-ItemProperty -LiteralPath $rk -Name $vn -Force -ErrorAction Stop
                        Write-Host "  removed Run value: $rk :: $vn" -ForegroundColor Green
                        $script:RemovedCount++
                    } catch {
                        Write-Host "  FAILED Run value ${vn}: $($_.Exception.Message)" -ForegroundColor Yellow
                        $script:FailedCount++
                    }
                }
            }
        }
        # Also remove any Run value whose data points at ZubCut.exe
        $props = Get-ItemProperty -LiteralPath $rk -ErrorAction SilentlyContinue
        if ($props) {
            foreach ($prop in $props.PSObject.Properties) {
                if ($prop.Name -in @('PSPath', 'PSParentPath', 'PSChildName', 'PSDrive', 'PSProvider')) { continue }
                $val = [string]$prop.Value
                if ($val -match '(?i)ZubCut\.exe') {
                    if (-not $AlsoControlPanel -and $val -match '(?i)ControlPanel|License') { continue }
                    if ($PSCmdlet.ShouldProcess("$rk\$($prop.Name)", 'Remove Run value pointing at ZubCut.exe')) {
                        try {
                            Remove-ItemProperty -LiteralPath $rk -Name $prop.Name -Force -ErrorAction Stop
                            Write-Host "  removed Run value: $rk :: $($prop.Name)" -ForegroundColor Green
                            $script:RemovedCount++
                        } catch {
                            Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Yellow
                            $script:FailedCount++
                        }
                    }
                }
            }
        }
    }

    $layerKeys = @(
        'HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers',
        'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'
    )
    foreach ($lk in $layerKeys) {
        if (-not (Test-Path -LiteralPath $lk)) { continue }
        $props = Get-ItemProperty -LiteralPath $lk -ErrorAction SilentlyContinue
        if (-not $props) { continue }
        foreach ($prop in $props.PSObject.Properties) {
            if ($prop.Name -in @('PSPath', 'PSParentPath', 'PSChildName', 'PSDrive', 'PSProvider')) { continue }
            if ($prop.Name -notmatch '(?i)ZubCut') { continue }
            if (-not $AlsoControlPanel -and $prop.Name -match '(?i)ControlPanel|License') { continue }
            if ($PSCmdlet.ShouldProcess("$lk :: $($prop.Name)", 'Remove AppCompatFlags Layers value')) {
                try {
                    Remove-ItemProperty -LiteralPath $lk -Name $prop.Name -Force -ErrorAction Stop
                    Write-Host "  removed Layers: $($prop.Name)" -ForegroundColor Green
                    $script:RemovedCount++
                } catch {
                    Write-Host "  FAILED Layers: $($_.Exception.Message)" -ForegroundColor Yellow
                    $script:FailedCount++
                }
            }
        }
    }
}

function Remove-OrphanUninstallKeys {
    Write-Step 'Removing leftover Uninstall registry keys'
    foreach ($entry in (Get-UninstallEntries)) {
        if (Test-Path -LiteralPath $entry.KeyPath) {
            Remove-PathSafe $entry.KeyPath "uninstall key $($entry.DisplayName)"
        }
    }
}

function Find-StrayZubCutExes {
    Write-Step 'Searching common folders for stray ZubCut.exe (old sticky copies)'
    $roots = @(
        [Environment]::GetFolderPath('Desktop'),
        [Environment]::GetFolderPath('MyDocuments'),
        (Join-Path $env:USERPROFILE 'Downloads'),
        (Join-Path $env:USERPROFILE 'Desktop'),
        (Join-Path $env:USERPROFILE 'Documents'),
        (Join-Path $env:USERPROFILE 'OneDrive'),
        (Join-Path $env:USERPROFILE 'OneDrive\Desktop'),
        (Join-Path $env:USERPROFILE 'OneDrive\Downloads'),
        (Join-Path $env:USERPROFILE 'OneDrive\Documents'),
        (Join-Path $env:PUBLIC 'Desktop'),
        (Join-Path $env:PUBLIC 'Downloads')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

    $found = @()
    foreach ($root in $roots) {
        # Depth-limited search keeps this fast on large OneDrive trees
        try {
            $found += Get-ChildItem -LiteralPath $root -Filter 'ZubCut.exe' -Recurse -Force -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.FullName -notmatch '(?i)\\GitHub\\' -and
                    $_.FullName -notmatch '(?i)\\ArpCut' -and
                    ($AlsoControlPanel -or $_.DirectoryName -notmatch '(?i)ControlPanel|License')
                }
        } catch { }
    }

    # Known install locations (in case uninstaller left the EXE)
    foreach ($extra in @(
            (Join-Path ${env:ProgramFiles} 'ZubCut\ZubCut.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'ZubCut\ZubCut.exe')
        )) {
        if ($extra -and (Test-Path -LiteralPath $extra)) {
            $found += Get-Item -LiteralPath $extra -ErrorAction SilentlyContinue
        }
    }

    $found = $found | Sort-Object FullName -Unique
    if (-not $found) {
        Write-Done 'No stray ZubCut.exe found in common folders.'
        return
    }
    foreach ($f in $found) {
        Write-Host "  found stray: $($f.FullName) ($([math]::Round($f.Length/1KB)) KB, $($f.LastWriteTime))" -ForegroundColor Yellow
        Remove-PathSafe $f.FullName 'stray executable'
        # If it was a one-file drop next to nothing, also drop adjacent updater crumbs
        $dir = $f.DirectoryName
        if ($dir -and (Test-Path -LiteralPath (Join-Path $dir '_internal'))) {
            Remove-PathSafe (Join-Path $dir '_internal') 'adjacent onedir runtime'
        }
        if ($dir -and (Test-Path -LiteralPath (Join-Path $dir '_internal.bak_zubcut'))) {
            Remove-PathSafe (Join-Path $dir '_internal.bak_zubcut') 'failed-update backup'
        }
    }
}

function Remove-UserDataAndTemp {
    Write-Step 'Removing user data and updater temp files'
    if (-not $KeepUserData) {
        $appData = Join-Path $env:APPDATA 'ZubCut'
        # Never wipe Control Panel accounts/signing key unless explicitly requested.
        # These live under the same AppData folder as client settings.
        $preserveNames = @(
            'paid-license-admin.json',
            'paid-license-signing.key',
            'license-manager-cloud-sync.json'
        )
        if ($WipeControlPanelData) {
            Remove-PathSafe $appData 'settings / license / Control Panel data / AppData'
        } elseif (Test-Path -LiteralPath $appData) {
            Get-ChildItem -LiteralPath $appData -Force -ErrorAction SilentlyContinue |
                Where-Object { $preserveNames -notcontains $_.Name } |
                ForEach-Object {
                    Remove-PathSafe $_.FullName 'client AppData (Control Panel accounts preserved)'
                }
            $kept = @(Get-ChildItem -LiteralPath $appData -Force -ErrorAction SilentlyContinue |
                Where-Object { $preserveNames -contains $_.Name } |
                Select-Object -ExpandProperty Name)
            if ($kept.Count -gt 0) {
                Write-Done ("Preserved Control Panel files: " + ($kept -join ', '))
                Write-Done 'Pass -WipeControlPanelData to delete those too.'
            } else {
                Write-Done 'No Control Panel account files were present to preserve.'
            }
            # Remove empty AppData folder if nothing left
            $left = @(Get-ChildItem -LiteralPath $appData -Force -ErrorAction SilentlyContinue)
            if ($left.Count -eq 0) {
                Remove-PathSafe $appData 'empty AppData folder'
            }
        }
        Remove-PathSafe (Join-Path $env:LOCALAPPDATA 'ZubCut') 'LocalAppData cache'
        # Legacy elmocut settings that can confuse migrations
        $legacy = Join-Path $env:USERPROFILE 'elmocut'
        if (Test-Path -LiteralPath $legacy) {
            Remove-PathSafe $legacy 'legacy elmocut user folder'
        }
    } else {
        Write-Done 'Keeping user data (-KeepUserData).'
    }

    $tempBits = @(
        (Join-Path $env:TEMP 'ZubCut-updater-debug.log'),
        (Join-Path $env:TEMP 'zubcut-update-waiter.ps1'),
        (Join-Path $env:TEMP 'ZubCut-signin-last.log'),
        (Join-Path $env:TEMP 'ZubCut'),
        (Join-Path $env:TEMP 'zubcut-ci-watch.log')
    )
    Get-ChildItem -LiteralPath $env:TEMP -Filter 'ZubCut-Setup*.exe' -Force -ErrorAction SilentlyContinue |
        ForEach-Object { $tempBits += $_.FullName }
    Get-ChildItem -LiteralPath $env:TEMP -Filter 'zubcut*.exe' -Force -ErrorAction SilentlyContinue |
        ForEach-Object { $tempBits += $_.FullName }

    foreach ($t in ($tempBits | Select-Object -Unique)) {
        Remove-PathSafe $t 'temp leftover'
    }
}

function Show-FinalCheck {
    Write-Step 'Final check'
    $still = @()
    foreach ($p in @(
            (Join-Path ${env:ProgramFiles} 'ZubCut'),
            (Join-Path ${env:ProgramFiles(x86)} 'ZubCut'),
            (Join-Path $env:APPDATA 'ZubCut')
        )) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            if ($KeepUserData -and $p -eq (Join-Path $env:APPDATA 'ZubCut')) { continue }
            # Control Panel account files left behind on purpose are OK.
            if (-not $WipeControlPanelData -and $p -eq (Join-Path $env:APPDATA 'ZubCut')) {
                $preserveNames = @(
                    'paid-license-admin.json',
                    'paid-license-signing.key',
                    'license-manager-cloud-sync.json'
                )
                $others = @(Get-ChildItem -LiteralPath $p -Force -ErrorAction SilentlyContinue |
                    Where-Object { $preserveNames -notcontains $_.Name })
                if ($others.Count -eq 0) { continue }
            }
            $still += $p
        }
    }
    $procs = @(Get-Process -Name 'ZubCut' -ErrorAction SilentlyContinue)
    if ($procs) { $still += "process still running: $($procs.Id -join ', ')" }

    $entries = @(Get-UninstallEntries)
    foreach ($e in $entries) { $still += "uninstall key: $($e.DisplayName) [$($e.KeyLeaf)]" }

    if ($still.Count -eq 0) {
        Write-Host "  Clean. No ZubCut install leftovers detected." -ForegroundColor Green
    } else {
        Write-Host "  Still present (may need reboot or manual delete):" -ForegroundColor Yellow
        $still | ForEach-Object { Write-Host "    - $_" -ForegroundColor Yellow }
    }
}

# ---- main ----
$script:RemovedCount = 0
$script:FailedCount = 0

Write-Host ''
Write-Host 'ZubCut complete uninstall' -ForegroundColor White
Write-Host 'Removes install files, shortcuts, autostart, stray EXEs, and (by default) client AppData.' -ForegroundColor DarkGray
Write-Host 'Control Panel account DB + signing key are KEPT unless -WipeControlPanelData.' -ForegroundColor DarkGray
Write-Host 'Npcap is left installed.' -ForegroundColor DarkGray
if ($KeepUserData) { Write-Host 'Mode: KeepUserData' -ForegroundColor DarkYellow }
if ($WipeControlPanelData) { Write-Host 'Mode: WipeControlPanelData (DELETES accounts/signing key)' -ForegroundColor Red }
if ($AlsoControlPanel) { Write-Host 'Mode: AlsoControlPanel' -ForegroundColor DarkYellow }
if (-not (Test-IsAdmin)) {
    Write-Host ''
    Write-Host 'WARNING: Not running as Administrator. Program Files / HKLM cleanup may fail.' -ForegroundColor Yellow
    Write-Host 'Prefer: right-click Uninstall-ZubCut-Completely.bat -> Run as administrator' -ForegroundColor Yellow
}

Stop-ZubCutProcesses

Write-Step 'Running official uninstallers (if registered)'
$entries = @(Get-UninstallEntries)
if (-not $entries) {
    Write-Done 'No ZubCut uninstall registry entries found.'
} else {
    foreach ($e in $entries) {
        Write-Host "  found: $($e.DisplayName) [$($e.KeyLeaf)]" -ForegroundColor Yellow
        $cmd = if ($e.QuietUninstall) { $e.QuietUninstall } else { $e.UninstallString }
        [void](Invoke-InnoUninstall $cmd)
        if ($e.InstallLocation) { Remove-PathSafe $e.InstallLocation 'InstallLocation' }
    }
    Start-Sleep -Seconds 1
}

Remove-InstallFolders
Remove-ShortcutsAndStartup
Remove-RegistryLaunchEntries
Remove-OrphanUninstallKeys
Find-StrayZubCutExes
Remove-UserDataAndTemp
Show-FinalCheck

Write-Host ''
Write-Host "Done. Removed/updated items: $RemovedCount  Failures: $FailedCount" -ForegroundColor White
Write-Host 'Next: install the NEW ZubCut setup as Administrator, then launch from Start Menu (not an old desktop icon).' -ForegroundColor Cyan
Write-Host "Settings should show Install Latest Build - never Updates Disabled." -ForegroundColor Cyan
Write-Host ''
