# Restore instant Kill ON / Lag / Dupe after Driver Easy reset Intel I219-LM +
# Intel chipset (PCIe Controller, PCI Express Root Port, PMC) drivers. Targets
# the three things that cause first-packet wake-up latency:
#   1. NIC "Allow the computer to turn off this device to save power" (PnPCapabilities)
#   2. PCIe ASPM Link State Power Management (active power plan)
#   3. Win10Pcap binding (Npcap is enough; Win10Pcap intercept adds first-send delay)
# Run as Administrator.
$ErrorActionPreference = 'Continue'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: must run as Administrator.' -ForegroundColor Red
    exit 1
}

$adapter = Get-NetAdapter -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceDescription -match 'I219|Ethernet Connection' -and $_.Status -eq 'Up' } |
    Select-Object -First 1
if (-not $adapter) {
    Write-Host 'No active Intel Ethernet adapter found.' -ForegroundColor Red
    exit 1
}
Write-Host ('Adapter: ' + $adapter.Name + '   ' + $adapter.InterfaceDescription) -ForegroundColor Cyan

# --- 1. Disable "Allow the computer to turn off this device" + Wake-on-LAN/Pattern
Write-Host '' 
Write-Host '[1/4] Disabling NIC selective suspend + WoL ...' -ForegroundColor Cyan
try {
    Set-NetAdapterPowerManagement -Name $adapter.Name `
        -AllowComputerToTurnOffDevice Disabled `
        -WakeOnMagicPacket Disabled `
        -WakeOnPattern Disabled `
        -DeviceSleepOnDisconnect Disabled `
        -ErrorAction Stop
    Write-Host '  Set-NetAdapterPowerManagement OK' -ForegroundColor Green
} catch {
    Write-Host ('  Set-NetAdapterPowerManagement failed: ' + $_.Exception.Message) -ForegroundColor Yellow
    Write-Host '  Falling back to registry PnPCapabilities = 0x118 (no PM, no wake)...'
    $guid = $adapter.InterfaceGuid
    $classRoot = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4D36E972-E325-11CE-BFC1-08002BE10318}'
    Get-ChildItem $classRoot -ErrorAction SilentlyContinue | ForEach-Object {
        $netCfg = (Get-ItemProperty $_.PSPath -Name 'NetCfgInstanceId' -ErrorAction SilentlyContinue).NetCfgInstanceId
        if ($netCfg -eq $guid) {
            Set-ItemProperty $_.PSPath -Name 'PnPCapabilities' -Value 0x118 -Type DWord -ErrorAction Continue
            Write-Host ('  Registry PnPCapabilities=0x118 written at ' + $_.PSChildName) -ForegroundColor Green
        }
    }
}

# --- 2. PCIe ASPM Link State Power Management -> Off (active power plan)
Write-Host ''
Write-Host '[2/4] Forcing PCIe ASPM = Off in active power plan ...' -ForegroundColor Cyan
# SUB_PCIEXPRESS = 501a4d13-42af-4429-9fd1-a8218c268e20
# ASPM            = ee12f906-d277-404b-b6da-e5fa1a576df5
$null = powercfg /SETACVALUEINDEX SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20 ee12f906-d277-404b-b6da-e5fa1a576df5 0
$null = powercfg /SETDCVALUEINDEX SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20 ee12f906-d277-404b-b6da-e5fa1a576df5 0
$null = powercfg /SETACTIVE SCHEME_CURRENT
Write-Host '  PCIe ASPM AC + DC = Off' -ForegroundColor Green

# --- 3. Unbind Win10Pcap (Npcap is sufficient; Win10Pcap intercepts every send)
Write-Host ''
Write-Host '[3/4] Disabling Win10Pcap binding on the adapter (Npcap stays bound) ...' -ForegroundColor Cyan
try {
    $bind = Get-NetAdapterBinding -Name $adapter.Name -ComponentID Win10Pcap -ErrorAction Stop
    if ($bind.Enabled) {
        Disable-NetAdapterBinding -Name $adapter.Name -ComponentID Win10Pcap -ErrorAction Stop
        Write-Host '  Win10Pcap binding disabled' -ForegroundColor Green
    } else {
        Write-Host '  Win10Pcap already disabled' -ForegroundColor Green
    }
} catch {
    Write-Host ('  Win10Pcap not bound (skip): ' + $_.Exception.Message) -ForegroundColor DarkYellow
}

# --- 4. Bounce the NIC so all of the above takes effect immediately
Write-Host ''
Write-Host '[4/4] Bouncing NIC...' -ForegroundColor Cyan
Restart-NetAdapter -Name $adapter.Name -Confirm:$false -ErrorAction Continue
Start-Sleep -Seconds 4

# --- Verification
Write-Host ''
Write-Host 'Result:' -ForegroundColor Cyan
try {
    Get-NetAdapterPowerManagement -Name $adapter.Name -ErrorAction Stop |
        Format-List AllowComputerToTurnOffDevice, WakeOnMagicPacket, WakeOnPattern, DeviceSleepOnDisconnect, Selective*
} catch {
    Write-Host ('  Get-NetAdapterPowerManagement still failing: ' + $_.Exception.Message) -ForegroundColor Yellow
    Write-Host '  Check Device Manager -> Ethernet 2 -> Power Management tab manually.'
}
Write-Host ''
$aspm = powercfg /QUERY SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20 ee12f906-d277-404b-b6da-e5fa1a576df5
$aspm | Select-String 'Current AC Power Setting Index|Current DC Power Setting Index'

Write-Host ''
Write-Host 'Done. Restart ZubCut and test Kill ON.' -ForegroundColor Green
