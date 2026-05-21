# Persistent Wi-Fi band lock (2.4 GHz until unlock). Dot-source from Lock/Unlock scripts.
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')

$script:WifiBandLockTaskName = 'ZubCut-WifiBandLock'
$script:WifiBandLockStateDir = Join-Path $env:LOCALAPPDATA 'ZubCut'
$script:WifiBandLockStateFile = Join-Path $script:WifiBandLockStateDir 'wifi-band-lock.json'

function Get-WifiBandLockStatePath {
    return $script:WifiBandLockStateFile
}

function Get-WifiConnectedSsid {
    $ifaces = netsh wlan show interfaces 2>$null | Out-String
    if ($ifaces -match 'SSID\s*:\s*(.+)\r?\n') { return $Matches[1].Trim() }
    $prof = netsh wlan show profiles 2>$null | Out-String
    if ($prof -match 'All User Profile\s*:\s*(.+)\r?\n') { return $Matches[1].Trim() }
    return $null
}

function Get-AllBssidsForSsidByBand {
    param(
        [Parameter(Mandatory)][string]$Ssid,
        [ValidateSet('2.4', '5')]
        [string]$Band
    )
    $scan = netsh wlan show networks mode=bssid 2>$null | Out-String
    $blocks = $scan -split '(?=SSID\s+\d+\s*:)'
    $ssidPat = [regex]::Escape($Ssid)
    $list = New-Object System.Collections.Generic.List[string]
    foreach ($block in $blocks) {
        if ($block -notmatch "SSID\s*(?:\d+\s*)?:\s*$ssidPat") { continue }
        foreach ($part in ($block -split 'BSSID \d+\s*:')) {
            if ($part -notmatch '([0-9a-f]{2}(?::[0-9a-f]{2}){5})') { continue }
            $bssid = $Matches[1].ToLower()
            $chB = 0
            if ($part -match 'Channel\s*:\s*(\d+)') { $chB = [int]$Matches[1] }
            $is24 = ($chB -ge 1 -and $chB -le 14)
            $is5 = ($chB -gt 14)
            if ($Band -eq '2.4' -and -not $is24) { continue }
            if ($Band -eq '5' -and -not $is5) { continue }
            if (-not $list.Contains($bssid)) { [void]$list.Add($bssid) }
        }
    }
    return @($list)
}

function Add-Wifi5GhzBlockFilters {
    param(
        [Parameter(Mandatory)][string]$Ssid,
        [string[]]$Bssids
    )
    $added = New-Object System.Collections.Generic.List[string]
    foreach ($bssid in @($Bssids)) {
        if (-not $bssid) { continue }
        $b = $bssid.ToLower()
        netsh wlan add filter permission=block ssid="$Ssid" bssid="$b" networktype=infrastructure 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { [void]$added.Add($b) }
    }
    return @($added)
}

function Remove-WifiBandBlockFilters {
    param(
        [Parameter(Mandatory)][string]$Ssid,
        [string[]]$BlockedBssids
    )
    foreach ($bssid in @($BlockedBssids)) {
        if (-not $bssid) { continue }
        netsh wlan delete filter permission=block ssid="$Ssid" bssid="$bssid" networktype=infrastructure 2>$null | Out-Null
    }
}

function Get-WifiBandLockState {
    $path = Get-WifiBandLockStatePath
    if (-not (Test-Path $path)) { return $null }
    try {
        return (Get-Content -Path $path -Raw -Encoding UTF8 | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Save-WifiBandLockState {
    param([hashtable]$State)
    $dir = Split-Path (Get-WifiBandLockStatePath) -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    ($State | ConvertTo-Json) | Set-Content -Path (Get-WifiBandLockStatePath) -Encoding UTF8 -Force
}

function Clear-WifiBandLockState {
    $path = Get-WifiBandLockStatePath
    if (Test-Path $path) { Remove-Item -Path $path -Force -ErrorAction SilentlyContinue }
}

function Connect-WifiUplinkTo24Ghz {
    param([string]$Ssid)
    if (-not $Ssid) { $Ssid = Get-WifiConnectedSsid }
    if (-not $Ssid) { return $false }
    $ch = Get-WifiUplinkChannel
    if ($ch -ge 1 -and $ch -le 14) { return $true }
    Stop-MobileHotspotIfOn | Out-Null
    Start-Sleep -Seconds 2
    $iface = Get-WifiClientInterfaceName
    netsh wlan disconnect interface="$iface" 2>$null | Out-Null
    Start-Sleep -Seconds 2
    $target = Find-BssidForSsidBand -Ssid $Ssid -Band '2.4'
    if (-not $target) { return $false }
    netsh wlan connect name="$($target.Ssid)" ssid="$($target.Ssid)" interface="$iface" bss="$($target.Bssid)" 2>$null | Out-Null
    Start-Sleep -Seconds 8
    $ch2 = Get-WifiUplinkChannel
    return ($ch2 -ge 1 -and $ch2 -le 14)
}

function Register-WifiBandLockWatchdog {
    $enforce = Join-Path $PSScriptRoot '_wifi_band_lock_enforce.ps1'
    if (-not (Test-Path $enforce)) { throw "Missing watchdog script: $enforce" }
    Unregister-WifiBandLockWatchdog
    $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$enforce`""
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg
    $start = (Get-Date).AddMinutes(1)
    $trigger = New-ScheduledTaskTrigger -Once -At $start `
        -RepetitionInterval (New-TimeSpan -Minutes 2) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $script:WifiBandLockTaskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
}

function Unregister-WifiBandLockWatchdog {
    Unregister-ScheduledTask -TaskName $script:WifiBandLockTaskName -Confirm:$false -ErrorAction SilentlyContinue
}

function Test-WifiBandLockActive {
    $st = Get-WifiBandLockState
    return ($null -ne $st -and [string]$st.band -eq '2.4')
}

function Invoke-WifiBandLockEnforce {
    param([switch]$Quiet)
    $st = Get-WifiBandLockState
    if ($null -eq $st -or [string]$st.band -ne '2.4') { return $true }
    $ssid = [string]$st.ssid
    if (-not $ssid) { return $false }

    $blocked = @()
    if ($st.blocked5Bssids) { $blocked = @($st.blocked5Bssids) }
    $scan5 = Get-AllBssidsForSsidByBand -Ssid $ssid -Band '5'
    $newBlocks = Add-Wifi5GhzBlockFilters -Ssid $ssid -Bssids $scan5
    foreach ($b in $newBlocks) {
        if ($blocked -notcontains $b) { $blocked += $b }
    }

    $ch = Get-WifiUplinkChannel
    $on24 = ($ch -ge 1 -and $ch -le 14)
    if (-not $on24) {
        if (-not (Connect-WifiUplinkTo24Ghz -Ssid $ssid)) {
            if (-not $Quiet) { Write-Host "Watchdog: still not on 2.4 GHz (channel $ch)." }
            return $false
        }
        $on24 = $true
    }

    $b24 = Find-BssidForSsidBand -Ssid $ssid -Band '2.4'
    $state = @{
        band            = '2.4'
        ssid            = $ssid
        bssid24         = if ($b24) { $b24.Bssid } else { [string]$st.bssid24 }
        blocked5Bssids  = $blocked
        lockedAt        = if ($st.lockedAt) { $st.lockedAt } else { (Get-Date).ToString('o') }
        lastEnforcedAt  = (Get-Date).ToString('o')
    }
    Save-WifiBandLockState -State $state
    if (-not $Quiet) {
        $ch2 = Get-WifiUplinkChannel
        Write-Host "Wi-Fi lock OK: $ssid on channel $ch2 (2.4 GHz), $($blocked.Count) x 5 GHz BSSID(s) blocked."
    }
    return $true
}

function Enable-WifiBandLock24Ghz {
    $ssid = Get-WifiConnectedSsid
    if (-not $ssid) {
        Write-Host 'ERROR: Not connected to Wi-Fi. Connect to your network first.'
        return $false
    }

    Write-Host "Locking PC Wi-Fi to 2.4 GHz for SSID: $ssid"
    Write-Host 'Blocking 5 GHz BSSIDs so Windows cannot auto-switch back...'
    $scan5 = Get-AllBssidsForSsidByBand -Ssid $ssid -Band '5'
    $blocked = Add-Wifi5GhzBlockFilters -Ssid $ssid -Bssids $scan5
    if ($blocked.Count -eq 0) {
        Write-Host 'WARNING: No 5 GHz BSSIDs seen in scan — lock will still use a 2-minute watchdog.'
    } else {
        Write-Host "Blocked $($blocked.Count) x 5 GHz BSSID(s)."
    }

    Stop-MobileHotspotIfOn | Out-Null
    Start-Sleep -Seconds 2
    if (-not (Connect-WifiUplinkTo24Ghz -Ssid $ssid)) {
        Write-Host 'FAILED: Could not connect to 2.4 GHz. Pick the 2.4 band in Settings -> Wi-Fi, then run this again.'
        Remove-WifiBandBlockFilters -Ssid $ssid -BlockedBssids $blocked
        return $false
    }

    $b24 = Find-BssidForSsidBand -Ssid $ssid -Band '2.4'
    $ch = Get-WifiUplinkChannel
    Save-WifiBandLockState -State @{
        band           = '2.4'
        ssid           = $ssid
        bssid24        = if ($b24) { $b24.Bssid } else { '' }
        blocked5Bssids = @($blocked)
        lockedAt       = (Get-Date).ToString('o')
    }

    Register-WifiBandLockWatchdog
    Write-Host "SUCCESS: Locked to 2.4 GHz (channel $ch). Stays until you run Unlock on the desktop."
    Write-Host 'When done: run "Unlock WiFi 5 GHz" (stops hotspot + restores 5 GHz).'
    Write-Host "Watchdog task: $($script:WifiBandLockTaskName) (every 2 min + after reboot)."
    Write-Host "State file: $(Get-WifiBandLockStatePath)"
    return $true
}

function Clear-AllUserWlanBlockFilters {
    $out = netsh wlan show filters 2>$null | Out-String
    $inUserBlock = $false
    foreach ($line in ($out -split "`r?`n")) {
        if ($line -match 'Block list on the system \(user\)') {
            $inUserBlock = $true
            continue
        }
        if ($inUserBlock -and $line -match '^\s*(Allow|Block) list on') {
            break
        }
        if ($inUserBlock -and $line -match '<None>') {
            break
        }
        if ($inUserBlock -and $line -match 'SSID\s*:\s*"([^"]+)".*BSSID\s*:\s*([0-9a-fA-F:]+)') {
            netsh wlan delete filter permission=block ssid="$($Matches[1])" bssid="$($Matches[2])" networktype=infrastructure 2>$null | Out-Null
        }
    }
}

function Disable-WifiBandLock {
    $st = Get-WifiBandLockState
    $ssid = if ($st -and $st.ssid) { [string]$st.ssid } else { Get-WifiConnectedSsid }
    Unregister-WifiBandLockWatchdog
    if ($ssid -and $st -and $st.blocked5Bssids) {
        Write-Host "Removing $($st.blocked5Bssids.Count) x 5 GHz block filter(s)..."
        Remove-WifiBandBlockFilters -Ssid $ssid -BlockedBssids @($st.blocked5Bssids)
    }
    Clear-WifiBandLockState
    Clear-AllUserWlanBlockFilters
    Write-Host 'Wi-Fi band lock removed.'
    return $ssid
}

function Restore-PcWifiNormal {
    <#
    Full recovery after 2.4 lock or PS5 hotspot: clear lock/watchdog/filters, stop hotspot,
    restart ICS if needed, reconnect PC uplink to 5 GHz (USB Wi-Fi cannot do hotspot + 5 GHz).
    #>
    param([switch]$Quiet)

    if (-not $Quiet) {
        Write-Host '=== Restore PC Wi-Fi (unlock + hotspot off + 5 GHz) ==='
    }

    $st = Get-WifiBandLockState
    $ssid = $null
    if ($st) {
        $ssid = Disable-WifiBandLock
    } else {
        Unregister-WifiBandLockWatchdog
        Clear-AllUserWlanBlockFilters
        $ssid = Get-WifiConnectedSsid
        if (-not $Quiet) {
            Write-Host 'No band-lock file — still clearing watchdog/filters and stopping hotspot.'
        }
    }

    if (-not $Quiet) {
        Write-Host 'Stopping mobile hotspot (required before 5 GHz on one USB Wi-Fi radio)...'
    }
    Stop-MobileHotspotIfOn | Out-Null
    Start-Sleep -Seconds 4
    Restart-IcssvcIfNeeded | Out-Null
    Start-Sleep -Seconds 2

    if (-not $ssid) { $ssid = Get-WifiConnectedSsid }

    $ok = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        if ($ssid -and (Connect-WifiUplinkTo5Ghz)) {
            $ch = Get-WifiUplinkChannel
            if ($ch -gt 14) {
                $ok = $true
                break
            }
        }
        if (-not $Quiet) {
            Write-Host "5 GHz reconnect attempt $attempt of 3..."
        }
        Start-Sleep -Seconds 3
    }

    $ch = Get-WifiUplinkChannel
    if (-not $Quiet) {
        if ($ok) {
            Write-Host "SUCCESS: Hotspot off, PC on 5 GHz (channel $ch, SSID $ssid)."
        } else {
            Write-Host "Hotspot is off. PC still on 2.4 GHz (channel $ch)."
            Write-Host 'In Settings -> Wi-Fi -> Wifi1, choose the 5 GHz network manually.'
        }
    }
    return $ok
}
