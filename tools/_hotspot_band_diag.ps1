$ErrorActionPreference = 'Continue'
Write-Host '=== Hotspot band deep diag ==='

Write-Host "`n--- Registry ---"
foreach ($rp in @(
    'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings',
    'HKCU:\Software\Microsoft\WCM\Tethering\Settings',
    'HKLM:\SOFTWARE\Microsoft\WcmSvc\Tethering',
    'HKCU:\Software\Microsoft\WcmSvc\Tethering'
)) {
    if (Test-Path $rp) {
        Write-Host "[$rp]"
        Get-ItemProperty $rp -ErrorAction SilentlyContinue |
            Format-List TetheringBand, WiFiBand, PreferredBand, Band, *Band* -ErrorAction SilentlyContinue
    }
}

Write-Host "`n--- Wi-Fi adapters ---"
Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Wi-Fi|Wireless|Direct' } |
    Format-Table Name, Status, LinkSpeed, InterfaceDescription -AutoSize

Write-Host "`n--- WinRT tethering ---"
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $p = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    $m = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($p)
    Write-Host "State=$($m.TetheringOperationalState)"
    Write-Host "Config.Band=$($m.Configuration.Band)"
    Write-Host "Config.SsidPrefix=$($m.Configuration.SsidPrefix)"
    Write-Host "MaxClientCount=$($m.MaxClientCount)"
    $ap = $m.GetCurrentAccessPointConfiguration()
    Write-Host "AP.Band=$($ap.Band)"
    Write-Host "AP.Ssid=$($ap.Ssid)"
    try {
        $caps = $m.GetTetheringCapability()
        Write-Host "Capability=$caps"
    } catch {}
} catch {
    Write-Host "WinRT: $($_.Exception.Message)"
}

Write-Host "`n--- netsh wlan ---"
netsh wlan show drivers 2>$null | Select-String -Pattern 'Hosted network|Hotspot|band|Band|802.11' -CaseSensitive:$false
netsh wlan show hostednetwork 2>$null

Write-Host "`n--- icssvc ---"
Get-Service icssvc, SharedAccess, WlanSvc | Format-Table Name, Status, StartType -AutoSize
