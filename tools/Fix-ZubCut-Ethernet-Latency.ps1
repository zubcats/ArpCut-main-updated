# Restore low-latency settings on the Intel Ethernet NIC after a driver reinstall
# wiped them (typical Driver Easy / fresh-install behaviour).
# Run as Administrator.
$ErrorActionPreference = 'Continue'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: must run as Administrator.' -ForegroundColor Red
    Write-Host 'Right-click PowerShell -> Run as administrator, then run this script.'
    exit 1
}

$adapter = Get-NetAdapter -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceDescription -match 'I219|Ethernet Connection' -and $_.Status -eq 'Up' } |
    Select-Object -First 1
if (-not $adapter) {
    Write-Host 'No Up Intel Ethernet adapter found.' -ForegroundColor Red
    exit 1
}
Write-Host ('Adapter: ' + $adapter.Name + '   ' + $adapter.InterfaceDescription) -ForegroundColor Cyan

function Set-Prop($display, $value) {
    try {
        $cur = Get-NetAdapterAdvancedProperty -Name $adapter.Name -DisplayName $display -ErrorAction Stop
        Set-NetAdapterAdvancedProperty -Name $adapter.Name -DisplayName $display -DisplayValue $value -NoRestart -ErrorAction Stop
        Write-Host ('  ' + $display + ' -> ' + $value)
    } catch {
        Write-Host ('  (skip) ' + $display + '  reason: ' + $_.Exception.Message) -ForegroundColor DarkYellow
    }
}

function Set-PropAny($display, $values) {
    foreach ($v in $values) {
        try {
            Set-NetAdapterAdvancedProperty -Name $adapter.Name -DisplayName $display -DisplayValue $v -NoRestart -ErrorAction Stop
            Write-Host ('  ' + $display + ' -> ' + $v)
            return
        } catch { }
    }
    Write-Host ('  (skip) ' + $display + '  - no accepted value among: ' + ($values -join ', ')) -ForegroundColor DarkYellow
}

Write-Host 'Applying low-latency profile...' -ForegroundColor Cyan
# Driver Easy often re-enables these after an Intel driver update — they add
# multi-second wake latency on the first ARP packet (Kill/Lag/Dupe all feel delayed).
Set-PropAny 'PCI Express Link Power Saving' @('Disabled', 'Off')
Set-PropAny 'Energy Efficient Ethernet'     @('Off','Disabled')
Set-PropAny 'Gigabit Master Slave Mode'     @('Force Master Mode')
Set-PropAny 'Green Ethernet'                @('Off','Disabled')
Set-PropAny 'Ultra Low Power Mode'          @('Off','Disabled')
Set-PropAny 'Power Saving Mode'             @('Off','Disabled')
Set-PropAny 'Reduce Speed On Power Down'    @('Off','Disabled')
Set-PropAny 'System Idle Power Saver'       @('Off','Disabled')
Set-Prop 'Interrupt Moderation'             'Disabled'
Set-PropAny 'Interrupt Moderation Rate'     @('Off', 'Disabled', 'Lowest', 'Low')
Set-PropAny 'Wake on Magic Packet'          @('Disabled', 'Off')
Set-PropAny 'Wake on Pattern Match'         @('Disabled', 'Off')
Set-Prop 'Large Send Offload V2 (IPv4)'     'Disabled'
Set-Prop 'Large Send Offload V2 (IPv6)'     'Disabled'
Set-PropAny 'Protocol ARP Offload'          @('Disabled', 'Off')
Set-PropAny 'Protocol NS Offload'           @('Disabled', 'Off')
Set-Prop 'Flow Control'                     'Disabled'
Set-Prop 'Receive Side Scaling'             'Enabled'
Set-Prop 'IPv4 Checksum Offload'            'Rx & Tx Enabled'
Set-Prop 'TCP Checksum Offload (IPv4)'      'Rx & Tx Enabled'
Set-Prop 'UDP Checksum Offload (IPv4)'      'Rx & Tx Enabled'
Set-Prop 'Receive Buffers'                  '2048'
Set-Prop 'Transmit Buffers'                 '2048'

Write-Host ''
Write-Host 'Disabling NIC selective suspend + WoL (Driver Easy resets these)...' -ForegroundColor Cyan
try {
    Set-NetAdapterPowerManagement -Name $adapter.Name `
        -AllowComputerToTurnOffDevice Disabled `
        -WakeOnMagicPacket Disabled `
        -WakeOnPattern Disabled `
        -DeviceSleepOnDisconnect Disabled `
        -ErrorAction Stop
    Write-Host '  Set-NetAdapterPowerManagement OK' -ForegroundColor Green
} catch {
    Write-Host ('  PowerManagement cmdlet failed: ' + $_.Exception.Message) -ForegroundColor Yellow
}

Write-Host 'Forcing PCIe ASPM = Off in active power plan...' -ForegroundColor Cyan
$null = powercfg /SETACVALUEINDEX SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20 ee12f906-d277-404b-b6da-e5fa1a576df5 0
$null = powercfg /SETDCVALUEINDEX SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20 ee12f906-d277-404b-b6da-e5fa1a576df5 0
$null = powercfg /SETACTIVE SCHEME_CURRENT
Write-Host '  PCIe ASPM AC + DC = Off' -ForegroundColor Green

Write-Host 'Disabling Win10Pcap binding (Npcap only — Win10Pcap adds send delay)...' -ForegroundColor Cyan
try {
    $bind = Get-NetAdapterBinding -Name $adapter.Name -ComponentID Win10Pcap -ErrorAction Stop
    if ($bind.Enabled) {
        Disable-NetAdapterBinding -Name $adapter.Name -ComponentID Win10Pcap -ErrorAction Stop
        Write-Host '  Win10Pcap disabled' -ForegroundColor Green
    } else {
        Write-Host '  Win10Pcap already disabled' -ForegroundColor Green
    }
} catch {
    Write-Host ('  Win10Pcap not bound (skip)') -ForegroundColor DarkYellow
}

Write-Host 'Bouncing the NIC so changes apply immediately...' -ForegroundColor Cyan
Restart-NetAdapter -Name $adapter.Name -Confirm:$false -ErrorAction Continue
Start-Sleep -Seconds 4

Write-Host 'Result:' -ForegroundColor Cyan
Get-NetAdapterAdvancedProperty -Name $adapter.Name -ErrorAction SilentlyContinue |
    Where-Object {
        $_.DisplayName -match 'PCI Express|Energy Efficient|Interrupt Moderation|Large Send|Flow Control|Receive Buffers|Transmit Buffers|Receive Side Scaling|Wake on'
    } |
    Format-Table DisplayName, DisplayValue -AutoSize -Wrap

Write-Host ''
Write-Host 'Done. Kill / Lag / Dupe should be instant again.' -ForegroundColor Green
Write-Host 'If ZubCut was open, restart it so it sees the bounced NIC.'
