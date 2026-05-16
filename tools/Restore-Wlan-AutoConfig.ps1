# Restore WLAN AutoConfig (WlanSvc) after an old ZubCut / Clumsy repair broke Wi-Fi.
# Right-click -> Run with PowerShell, or use Restore-Wlan-AutoConfig.cmd (runs as Admin).
$ErrorActionPreference = 'Continue'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: Run as Administrator (use Restore-Wlan-AutoConfig.cmd).'
    Read-Host 'Press Enter'
    exit 1
}

function Ensure-WlanAutoConfigHealthy {
    try {
        $wl = Get-Service -Name WlanSvc -ErrorAction Stop
        if ($wl.StartType -notin @('Automatic', 'AutomaticDelayedStart')) {
            Set-Service -Name WlanSvc -StartupType Automatic -ErrorAction SilentlyContinue
        }
        if ($wl.Status -ne 'Running') {
            Start-Service -Name WlanSvc -ErrorAction SilentlyContinue
        }
        return $true
    } catch {
        try { Set-Service -Name WlanSvc -StartupType Automatic -ErrorAction SilentlyContinue } catch {}
        try { Start-Service -Name WlanSvc -ErrorAction SilentlyContinue } catch {}
        return $true
    }
}

Write-Host '=== Restore WLAN AutoConfig (WlanSvc) ==='
Write-Host ''

$wl = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
if (-not $wl) {
    Write-Host 'WlanSvc is MISSING (not listed in services at all).'
    Write-Host 'Old ZubCut usually only stopped the service — missing means Windows Wi-Fi stack or driver damage.'
    Write-Host ''
    Write-Host 'Try in order (Admin Command Prompt), then reboot:'
    Write-Host '  sc query WlanSvc'
    Write-Host '  sfc /scannow'
    Write-Host '  DISM /Online /Cleanup-Image /RestoreHealth'
    Write-Host ''
    Write-Host 'Also: Device Manager -> Network adapters -> your Wi-Fi adapter:'
    Write-Host '  Enable if disabled, or Uninstall device -> reboot (reinstalls driver).'
    Write-Host ''
    Write-Host 'If there is NO Wi-Fi adapter in Device Manager, this PC may need a USB Wi-Fi dongle'
    Write-Host 'or the built-in radio failed — WLAN AutoConfig will not appear without hardware.'
    Read-Host 'Press Enter'
    exit 1
}

Write-Host ("Found: $($wl.DisplayName)  Status=$($wl.Status)  StartType=$($wl.StartType)")
Ensure-WlanAutoConfigHealthy | Out-Null
Start-Sleep -Seconds 2
$wl = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue

if ($wl.Status -eq 'Running' -and $wl.StartType -notin @('Manual', 'Disabled')) {
    Write-Host ''
    Write-Host 'SUCCESS: WLAN AutoConfig is Automatic and running.'
    Write-Host 'Open Settings -> Network -> Wi-Fi — networks should appear after a reboot if needed.'
    Read-Host 'Press Enter'
    exit 0
}

Write-Host ''
Write-Host 'Service exists but could not be fully restored.'
Write-Host 'Admin Command Prompt:'
Write-Host '  sc config WlanSvc start= auto'
Write-Host '  net start WlanSvc'
Write-Host 'Then reboot.'
if ($wl.StartType -eq 'Disabled') {
    Write-Host ''
    Write-Host 'If StartType is Disabled, run:  sc config WlanSvc start= demand'
    Write-Host 'then:  sc config WlanSvc start= auto'
}
Read-Host 'Press Enter'
exit 1
