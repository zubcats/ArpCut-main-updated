# One-shot local PC recovery after broken hotspot scripts (Admin, self-elevates)
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_local_hotspot_fix_log.txt'
function L([string]$m) { Write-Host $m; Add-Content $log $m -ErrorAction SilentlyContinue }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    L 'Click Yes on UAC...'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

'' | Set-Content $log -Force
L "=== Local hotspot recovery $(Get-Date -Format o) ==="

# Remove ZubCut stale state so startup does not touch network
$zcState = Join-Path $env:APPDATA 'ZubCut\clumsy_ics_state.json'
if (Test-Path $zcState) {
    Remove-Item $zcState -Force -ErrorAction SilentlyContinue
    L 'Removed stale ZubCut clumsy_ics_state.json'
}

foreach ($svc in @('WlanSvc', 'SharedAccess', 'icssvc', 'Dhcp')) {
    try {
        $s = Get-Service $svc -EA SilentlyContinue
        if ($s -and $s.Status -ne 'Running') {
            Set-Service $svc -StartupType Automatic -EA SilentlyContinue
            Start-Service $svc -EA SilentlyContinue
            L "Started $svc"
        }
    } catch {}
}

# Stale gateway on wrong NIC
Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' } | ForEach-Object {
    $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
    if ($a -and $a.InterfaceDescription -notmatch 'Direct|Hosted' -and $a.Name -notmatch 'Local Area Connection') {
        L "Remove stale 192.168.137.1 from $($a.Name)"
        Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -EA SilentlyContinue
    }
}

function NormGuid($g) {
    if ($null -eq $g) { return '' }
    return ($g.ToString().Trim('{', '}').ToLowerInvariant())
}

# WinRT tethering — start only if off
Add-Type -AssemblyName System.Runtime.WindowsRuntime -EA SilentlyContinue
[void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
[void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Length -eq 1 } | Select-Object -First 1
function Wait-Async($op, [int]$sec) {
    foreach ($iface in $op.GetType().GetInterfaces()) {
        if ($iface.IsGenericType -and $iface.GetGenericTypeDefinition().FullName -eq 'Windows.Foundation.IAsyncOperation`1') {
            $rt = $iface.GetGenericArguments()[0]
            $task = $asTask.MakeGenericMethod(@($rt)).Invoke($null, @($op))
            if ($task.Wait($sec * 1000)) { return $task.Result }
        }
    }
    return $null
}

$gwOk = [bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' })
$dhcpOk = [bool](Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue)
try {
    $prof = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if ($prof) {
        $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($prof)
        $st = $mgr.TetheringOperationalState.ToString()
        L "Tethering: $st (gw=$gwOk dhcp=$dhcpOk)"
        if ($st -ne 'On') {
            L 'Starting Mobile Hotspot...'
            $null = Wait-Async ($mgr.StartTetheringAsync()) 60
            Start-Sleep -Seconds 12
            L "After start: $($mgr.TetheringOperationalState)"
        } elseif (-not $gwOk -or -not $dhcpOk) {
            L 'Hotspot on but broken — one OFF/ON cycle...'
            $null = Wait-Async ($mgr.StopTetheringAsync()) 45
            Start-Sleep -Seconds 12
            $null = Wait-Async ($mgr.StartTetheringAsync()) 60
            Start-Sleep -Seconds 12
            L "After cycle: $($mgr.TetheringOperationalState)"
        }
    } else {
        L 'WARN: PC Wi-Fi not connected to internet — connect Wi-Fi first'
    }
} catch { L "Tethering error: $($_.Exception.Message)" }

$down = $null
for ($i = 0; $i -lt 12; $i++) {
    $down = Get-NetAdapter -EA SilentlyContinue | Where-Object {
        $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection')
    } | Select-Object -First 1
    if ($down) { break }
    Start-Sleep -Seconds 2
}
if (-not $down) {
    L 'ERROR: Hotspot adapter not Up — turn Mobile hotspot ON in Settings'
    Start-Process 'ms-settings:network-mobilehotspot'
    exit 2
}
L "Hotspot NIC: $($down.Name)"

# Undo IPv6-disable from earlier agent scripts
$v6 = Get-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
if ($v6 -and -not $v6.Enabled) {
    Enable-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
    L 'Re-enabled IPv6 on hotspot adapter'
}
Get-NetIPAddress -InterfaceIndex $down.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -like '169.254.*' } |
    ForEach-Object {
        Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -EA SilentlyContinue
        L "Removed APIPA $($_.IPAddress)"
    }
if (-not (Get-NetIPAddress -InterfaceIndex $down.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |
        Where-Object { $_.IPAddress -eq '192.168.137.1' })) {
    New-NetIPAddress -InterfaceIndex $down.ifIndex -IPAddress 192.168.137.1 -PrefixLength 24 -EA SilentlyContinue | Out-Null
    L 'Added 192.168.137.1'
}

$saParams = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
foreach ($n in @('ScopeAddress', 'ScopeAddressBackup', 'StandaloneDhcpAddress')) {
    Set-ItemProperty -Path $saParams -Name $n -Value '192.168.137.1' -Type String -Force -EA SilentlyContinue
}

$up = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and ($_.Name -eq 'Wi-Fi' -or $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi')
    $_.InterfaceDescription -notmatch 'Direct|Virtual|Bluetooth'
} | Select-Object -First 1
if ($up) {
    L "Internet NIC: $($up.Name)"
    $share = New-Object -ComObject HNetCfg.HNetShare
    $cm = @{}
    foreach ($conn in @($share.EnumEveryConnection())) {
        try {
            $p = $share.NetConnectionProps($conn)
            $cm[(NormGuid $p.Guid)] = $share.INetSharingConfigurationForINetConnection($conn)
        } catch {}
    }
    $upG = NormGuid $up.InterfaceGuid
    $dnG = NormGuid $down.InterfaceGuid
    if ($cm.ContainsKey($upG) -and $cm.ContainsKey($dnG)) {
        $icsOk = $false
        try {
            $u = $cm[$upG]; $d = $cm[$dnG]
            $icsOk = $u.SharingEnabled -and $d.SharingEnabled -and [int]$u.SharingConnectionType -eq 0 -and [int]$d.SharingConnectionType -eq 1
        } catch {}
        if ($icsOk) {
            L 'ICS already: Wi-Fi public -> hotspot private'
        } else {
            L 'Applying ICS (pair only)...'
            foreach ($g in @($upG, $dnG)) {
                try { if ($cm[$g].SharingEnabled) { $cm[$g].DisableSharing() } } catch {}
            }
            Start-Sleep -Seconds 1
            try {
                $cm[$upG].EnableSharing(0)
                $cm[$dnG].EnableSharing(1)
            } catch { L "ICS enable: $($_.Exception.Message)" }
            Start-Sleep -Seconds 4
        }
    }
}

foreach ($line in @(arp -a)) {
    if ($line -match '(192\.168\.137\.\d+)\s+([0-9a-fA-F\-]+)\s+static' -and $Matches[1] -notmatch '\.(1|255)$') {
        arp -d $Matches[1] 2>$null | Out-Null
        L "Cleared static ARP $($Matches[1])"
    }
}

Start-Service SharedAccess -EA SilentlyContinue
Start-Sleep -Seconds 4

L ''
L '=== RESULT ==='
$gw = [bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' })
$dhcp = [bool](Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue)
$v6e = (Get-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -EA SilentlyContinue).Enabled
L "  192.168.137.1: $gw"
L "  DHCP (UDP 67): $dhcp"
L "  Hotspot IPv6 binding: $v6e"
Get-NetIPAddress -InterfaceIndex $down.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |
    ForEach-Object { L "  IPv4: $($_.IPAddress)" }
if ($gw -and $dhcp) {
    L ''
    L 'SUCCESS. PS5: forget PC hotspot, reconnect. Test ZubCut AFTER PS5 has internet.'
    exit 0
}
L ''
L 'PARTIAL — toggle Mobile hotspot OFF 15s ON in Settings, then reconnect PS5.'
exit 1
