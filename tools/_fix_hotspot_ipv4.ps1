# Force IPv4 DHCP on PC Mobile Hotspot (PS5 "IPv6 only" message)
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_hotspot_ipv4_log.txt'
function L([string]$m) { Write-Host $m; Add-Content $log $m }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    L 'Elevating (click Yes on UAC)...'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}

'' | Set-Content $log
L "=== Fix hotspot IPv4 $(Get-Date -Format o) ==="

$down = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection')
} | Select-Object -First 1

if (-not $down) {
    L 'Hotspot adapter not Up — starting Mobile Hotspot...'
    $turnOn = Join-Path $PSScriptRoot '_run_hotspot_turn_on_fix.ps1'
    if (Test-Path $turnOn) { & $turnOn }
    $down = Get-NetAdapter -EA SilentlyContinue | Where-Object {
        $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection')
    } | Select-Object -First 1
}
if (-not $down) { L 'ERROR: No hotspot adapter'; exit 1 }

$ifIdx = $down.ifIndex
L "Hotspot: $($down.Name) (ifIndex $ifIdx)"

# --- Before ---
L '--- Before ---'
Get-NetIPAddress -InterfaceIndex $ifIdx -EA SilentlyContinue |
    Format-Table AddressFamily, IPAddress, PrefixLength -AutoSize | Out-String | ForEach-Object { L $_.TrimEnd() }

# Disable IPv6 on hotspot adapter only (PS5 needs IPv4 192.168.137.x)
L 'Disabling IPv6 on hotspot adapter...'
try {
    Disable-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -ErrorAction Stop
    L '  Disabled ms_tcpip6 binding'
} catch {
    L "  ms_tcpip6 bind: $($_.Exception.Message)"
}
try {
    Set-NetIPInterface -InterfaceIndex $ifIdx -AddressFamily IPv6 -InterfaceMetric 9999 -EA SilentlyContinue
    netsh interface ipv6 set interface "$ifIdx" routerdiscovery=disabled store=active 2>$null | Out-Null
    netsh interface ipv6 set interface "$ifIdx" managedaddress=disabled store=active 2>$null | Out-Null
} catch {}

# Ensure IPv4 gateway on hotspot
$v4 = Get-NetIPAddress -InterfaceIndex $ifIdx -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' }
if (-not $v4) {
    L 'Adding 192.168.137.1/24 on hotspot...'
    try {
        New-NetIPAddress -InterfaceIndex $ifIdx -IPAddress 192.168.137.1 -PrefixLength 24 -ErrorAction Stop | Out-Null
    } catch {
        L "  New-NetIPAddress: $($_.Exception.Message)"
    }
} else {
    L 'IPv4 192.168.137.1 already present'
}

# SharedAccess / ICS IPv4 scope
$saParams = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
foreach ($n in @('ScopeAddress', 'ScopeAddressBackup', 'StandaloneDhcpAddress')) {
    Set-ItemProperty -Path $saParams -Name $n -Value '192.168.137.1' -Type String -Force -EA SilentlyContinue
}
try {
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name 'IPEnableRouter' -Value 1 -Type DWord -Force
} catch {}

# Prefer IPv4 on hotspot interface
Set-NetIPInterface -InterfaceIndex $ifIdx -AddressFamily IPv4 -InterfaceMetric 10 -EA SilentlyContinue
Set-NetIPInterface -InterfaceIndex $ifIdx -AddressFamily IPv6 -InterfaceMetric 9999 -EA SilentlyContinue

# Firewall DHCP + subnet
foreach ($r in @(
    @{N='ZubCut-DHCP-In';D='in';P=67}, @{N='ZubCut-DHCP-Out';D='out';P=67},
    @{N='ZubCut-DHCPClient-In';D='in';P=68}, @{N='ZubCut-DHCPClient-Out';D='out';P=68}
)) {
    netsh advfirewall firewall delete rule name="$($r.N)" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="$($r.N)" dir=$($r.D) action=allow protocol=UDP localport=$($r.P) enable=yes | Out-Null
}
netsh advfirewall firewall delete rule name='ZubCut-Hotspot-Subnet-In' 2>$null | Out-Null
netsh advfirewall firewall add rule name='ZubCut-Hotspot-Subnet-In' dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null

# Re-apply ICS if needed
function NormGuid($g) {
    if ($null -eq $g) { return '' }
    return ($g.ToString().Trim('{', '}').ToLowerInvariant())
}
$up = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and ($_.Name -eq 'Wi-Fi' -or $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi')
    $_.InterfaceDescription -notmatch 'Direct|Virtual|Bluetooth'
} | Select-Object -First 1
if ($up) {
    $share = New-Object -ComObject HNetCfg.HNetShare
    $connMap = @{}
    foreach ($conn in @($share.EnumEveryConnection())) {
        try {
            $p = $share.NetConnectionProps($conn)
            $connMap[(NormGuid $p.Guid)] = $share.INetSharingConfigurationForINetConnection($conn)
        } catch {}
    }
    $upG = NormGuid $up.InterfaceGuid
    $dnG = NormGuid $down.InterfaceGuid
    if ($connMap.ContainsKey($upG) -and $connMap.ContainsKey($dnG)) {
        $uCfg = $connMap[$upG]; $dCfg = $connMap[$dnG]
        $ok = $false
        try {
            if ($uCfg.SharingEnabled -and $dCfg.SharingEnabled) {
                $ok = ([int]$uCfg.SharingConnectionType -eq 0 -and [int]$dCfg.SharingConnectionType -eq 1)
            }
        } catch {}
        if (-not $ok) {
            L 'Re-applying ICS (Wi-Fi public -> hotspot private)...'
            foreach ($k in $connMap.Keys) {
                try { if ($connMap[$k].SharingEnabled) { $connMap[$k].DisableSharing() } } catch {}
            }
            Start-Sleep -Seconds 1
            try {
                $connMap[$upG].EnableSharing(0)
                $connMap[$dnG].EnableSharing(1)
            } catch { L "  ICS: $($_.Exception.Message)" }
            Start-Sleep -Seconds 3
        } else {
            L 'ICS pair OK'
        }
    }
}

Start-Service SharedAccess -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5

# Brief hotspot toggle to refresh DHCP v4
Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction SilentlyContinue
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
try {
    $prof = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($prof)
    if ($mgr.TetheringOperationalState.ToString() -eq 'On') {
        L 'Toggling hotspot OFF 8s ON (refresh IPv4 DHCP)...'
        $null = Wait-Async ($mgr.StopTetheringAsync()) 30
        Start-Sleep -Seconds 8
        $null = Wait-Async ($mgr.StartTetheringAsync()) 45
        Start-Sleep -Seconds 10
    }
} catch { L "  Tether toggle: $($_.Exception.Message)" }

L '--- After ---'
Get-NetIPAddress -InterfaceIndex $ifIdx -EA SilentlyContinue |
    Format-Table AddressFamily, IPAddress, PrefixLength -AutoSize | Out-String | ForEach-Object { L $_.TrimEnd() }
$dhcp67 = [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue)
$gw137 = [bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' })
$v6bind = Get-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
L "192.168.137.1: $gw137"
L "DHCP UDP 67: $dhcp67"
L "IPv6 binding on hotspot: $($v6bind.Enabled)"
if ($gw137 -and $dhcp67 -and -not $v6bind.Enabled) {
    L 'SUCCESS — PS5 should see IPv4. Forget hotspot on PS5 and reconnect.'
    exit 0
}
L 'If PS5 still says IPv6 only: set manual IP 192.168.137.2 gateway 192.168.137.1'
exit 2
