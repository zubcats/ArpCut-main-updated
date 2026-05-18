# Full Mobile Hotspot recovery — run as Admin (self-elevates)
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_hotspot_repair_log.txt'
function L([string]$m) { Write-Host $m; Add-Content $log $m -ErrorAction SilentlyContinue }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    '' | Set-Content $log -Force
    L 'Click Yes on UAC...'
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if (Test-Path $log) { Get-Content $log }
    exit
}
'' | Set-Content $log -Force
L "=== Full hotspot repair $(Get-Date -Format o) ==="

# 1) Services
foreach ($svc in @('WlanSvc', 'SharedAccess', 'icssvc', 'Dhcp', 'NlaSvc')) {
    try {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s -and $s.Status -ne 'Running') {
            Set-Service -Name $svc -StartupType Automatic -ErrorAction SilentlyContinue
            Start-Service -Name $svc -ErrorAction SilentlyContinue
            L "Started $svc"
        }
    } catch { L "WARN $svc : $($_.Exception.Message)" }
}

# 2) Remove stale 192.168.137.1 from wrong NIC
Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' } | ForEach-Object {
    $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -EA SilentlyContinue
    if ($a -and $a.InterfaceDescription -notmatch 'Direct|Hosted' -and $a.Name -notmatch 'Local Area Connection') {
        L "Remove stale gw from $($a.Name)"
        Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -EA SilentlyContinue
    }
}

# 3) WinRT tethering — stop then start clean
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
$gwOk = [bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' })
$dhcpOk = [bool](Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue)
try {
    $prof = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if ($prof) {
        $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($prof)
        $state = $mgr.TetheringOperationalState.ToString()
        L "Tethering: $state (gw=$gwOk dhcp=$dhcpOk)"
        if ($state -ne 'On') {
            L 'Starting Mobile Hotspot...'
            $null = Wait-Async ($mgr.StartTetheringAsync()) 60
            Start-Sleep -Seconds 12
            L "Tethering after start: $($mgr.TetheringOperationalState)"
        } elseif (-not $gwOk -or -not $dhcpOk) {
            L 'Hotspot on but broken — one gentle OFF/ON cycle...'
            $null = Wait-Async ($mgr.StopTetheringAsync()) 45
            Start-Sleep -Seconds 12
            $null = Wait-Async ($mgr.StartTetheringAsync()) 60
            Start-Sleep -Seconds 12
            L "Tethering after cycle: $($mgr.TetheringOperationalState)"
        } else {
            L 'Hotspot already on with gateway+DHCP — leaving tethering alone'
        }
    } else {
        L 'WARN: No internet connection profile (connect PC Wi-Fi to router first)'
    }
} catch { L "Tethering: $($_.Exception.Message)" }

# 4) Wait for hotspot adapter
$down = $null
for ($i = 0; $i -lt 15; $i++) {
    $down = Get-NetAdapter -EA SilentlyContinue | Where-Object {
        $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection')
    } | Select-Object -First 1
    if ($down) { break }
    Start-Sleep -Seconds 2
}
if (-not $down) {
    L 'ERROR: Hotspot adapter never came Up. Open Settings -> Mobile hotspot -> turn ON manually.'
    Start-Process 'ms-settings:network-mobilehotspot'
    exit 2
}
L "Hotspot NIC: $($down.Name) ifIndex=$($down.ifIndex)"

# 5) Repair adapter (re-enable IPv6, drop APIPA, ensure gw)
$v6 = Get-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
if ($v6 -and -not $v6.Enabled) { Enable-NetAdapterBinding -Name $down.Name -ComponentID ms_tcpip6 -EA SilentlyContinue; L 'Re-enabled IPv6 binding' }
Get-NetIPAddress -InterfaceIndex $down.ifIndex -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -like '169.254.*' } |
    ForEach-Object { Remove-NetIPAddress -IPAddress $_.IPAddress -InterfaceIndex $_.InterfaceIndex -Confirm:$false -EA SilentlyContinue }
if (-not (Get-NetIPAddress -InterfaceIndex $down.ifIndex -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' })) {
    New-NetIPAddress -InterfaceIndex $down.ifIndex -IPAddress 192.168.137.1 -PrefixLength 24 -ErrorAction SilentlyContinue | Out-Null
}

# 6) ICS registry + firewall
$saParams = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
foreach ($n in @('ScopeAddress', 'ScopeAddressBackup', 'StandaloneDhcpAddress')) {
    Set-ItemProperty -Path $saParams -Name $n -Value '192.168.137.1' -Type String -Force -EA SilentlyContinue
}
foreach ($r in @(
    @{N='ZubCut-DHCP-In';D='in';P=67}, @{N='ZubCut-DHCP-Out';D='out';P=67},
    @{N='ZubCut-DHCPClient-In';D='in';P=68}, @{N='ZubCut-DHCPClient-Out';D='out';P=68}
)) {
    netsh advfirewall firewall delete rule name="$($r.N)" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="$($r.N)" dir=$($r.D) action=allow protocol=UDP localport=$($r.P) enable=yes | Out-Null
}
netsh advfirewall firewall delete rule name='ZubCut-Hotspot-Subnet-In' 2>$null | Out-Null
netsh advfirewall firewall add rule name='ZubCut-Hotspot-Subnet-In' dir=in action=allow remoteip=192.168.137.0/24 enable=yes | Out-Null

# 7) ICS on Wi-Fi -> hotspot (minimal wipe)
function NormGuid($g) {
    if ($null -eq $g) { return '' }
    return ($g.ToString().Trim('{', '}').ToLowerInvariant())
}
$up = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and ($_.Name -eq 'Wi-Fi' -or $_.InterfaceDescription -match 'Wireless LAN|Wi-Fi')
    $_.InterfaceDescription -notmatch 'Direct|Virtual|Bluetooth'
} | Select-Object -First 1
if ($up) {
    L "Upstream: $($up.Name)"
    $share = New-Object -ComObject HNetCfg.HNetShare
    $connMap = @{}
    foreach ($conn in @($share.EnumEveryConnection())) {
        try {
            $p = $share.NetConnectionProps($conn)
            $connMap[(NormGuid $p.Guid)] = @{ cfg = $share.INetSharingConfigurationForINetConnection($conn); name = $p.Name }
        } catch {}
    }
    $upG = NormGuid $up.InterfaceGuid
    $dnG = NormGuid $down.InterfaceGuid
    $upK = $null; $dnK = $null
    foreach ($k in $connMap.Keys) {
        if ($k -eq $upG) { $upK = $k }
        if ($k -eq $dnG) { $dnK = $k }
    }
    if ($upK -and $dnK) {
        $need = $true
        try {
            $uc = $connMap[$upK].cfg; $dc = $connMap[$dnK].cfg
            if ($uc.SharingEnabled -and $dc.SharingEnabled -and [int]$uc.SharingConnectionType -eq 0 -and [int]$dc.SharingConnectionType -eq 1) {
                $need = $false
                L 'ICS already correct'
            }
        } catch {}
        if ($need) {
            L 'Applying ICS...'
            foreach ($k in $connMap.Keys) {
                try { if ($connMap[$k].cfg.SharingEnabled) { $connMap[$k].cfg.DisableSharing() } } catch {}
            }
            Start-Sleep -Seconds 1
            try {
                $connMap[$upK].cfg.EnableSharing(0)
                $connMap[$dnK].cfg.EnableSharing(1)
            } catch { L "ICS: $($_.Exception.Message)" }
            Start-Sleep -Seconds 4
        }
    }
}

# 8) Clear stale static ARP
foreach ($line in @(arp -a)) {
    if ($line -match '(192\.168\.137\.\d+)\s+([0-9a-fA-F\-]+)\s+static' -and $Matches[1] -ne '192.168.137.1') {
        arp -d $Matches[1] 2>$null | Out-Null
        L "Cleared ARP $($Matches[1])"
    }
}

Start-Service SharedAccess -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5

L '--- Result ---'
L "gw137: $([bool](Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.137.1' }))"
L "dhcp67: $([bool](Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue))"
L "hotspot Up: $([bool]$down)"
Get-NetIPAddress -InterfaceIndex $down.ifIndex -AddressFamily IPv4 -EA SilentlyContinue | ForEach-Object { L "  IPv4: $($_.IPAddress)" }
L 'PS5: forget hotspot, reconnect. Manual: 192.168.137.2 gw 192.168.137.1 DNS 8.8.8.8'
