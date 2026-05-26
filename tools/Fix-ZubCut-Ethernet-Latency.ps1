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
Set-PropAny 'Energy Efficient Ethernet'     @('Off','Disabled')
Set-PropAny 'Gigabit Master Slave Mode'     @('Force Master Mode')
Set-PropAny 'Green Ethernet'                @('Off','Disabled')
Set-PropAny 'Ultra Low Power Mode'          @('Off','Disabled')
Set-PropAny 'Power Saving Mode'             @('Off','Disabled')
Set-PropAny 'Reduce Speed On Power Down'    @('Off','Disabled')
Set-PropAny 'System Idle Power Saver'       @('Off','Disabled')
Set-Prop 'Interrupt Moderation'             'Disabled'
Set-Prop 'Large Send Offload V2 (IPv4)'     'Disabled'
Set-Prop 'Large Send Offload V2 (IPv6)'     'Disabled'
Set-Prop 'Flow Control'                     'Disabled'
Set-Prop 'Receive Side Scaling'             'Enabled'
Set-Prop 'IPv4 Checksum Offload'            'Rx & Tx Enabled'
Set-Prop 'TCP Checksum Offload (IPv4)'      'Rx & Tx Enabled'
Set-Prop 'UDP Checksum Offload (IPv4)'      'Rx & Tx Enabled'
Set-Prop 'Receive Buffers'                  '2048'
Set-Prop 'Transmit Buffers'                 '2048'

Write-Host 'Bouncing the NIC so changes apply immediately...' -ForegroundColor Cyan
Restart-NetAdapter -Name $adapter.Name -Confirm:$false -ErrorAction Continue
Start-Sleep -Seconds 4

Write-Host 'Result:' -ForegroundColor Cyan
Get-NetAdapterAdvancedProperty -Name $adapter.Name -ErrorAction SilentlyContinue |
    Where-Object {
        $_.DisplayName -match 'Energy Efficient|Interrupt Moderation|Large Send|Flow Control|Receive Buffers|Transmit Buffers|Receive Side Scaling'
    } |
    Format-Table DisplayName, DisplayValue -AutoSize -Wrap

Write-Host ''
Write-Host 'Done. Kill / Lag / Dupe should be instant again.' -ForegroundColor Green
Write-Host 'If ZubCut was open, restart it so it sees the bounced NIC.'
