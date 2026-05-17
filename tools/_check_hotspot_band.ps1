$ErrorActionPreference = 'Continue'
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
    Write-Output ("STATE=" + $mgr.TetheringOperationalState)
    Write-Output ("BAND=" + $mgr.Configuration.Band)
    Write-Output ("SSID=" + $mgr.Configuration.SsidPrefix)
    try {
        $ap = $mgr.GetCurrentAccessPointConfiguration()
        Write-Output ("AP_BAND=" + $ap.Band)
        Write-Output ("AP_SSID=" + $ap.Ssid)
    } catch {
        Write-Output ("AP_ERR=" + $_.Exception.Message)
    }
} catch {
    Write-Output ("ERR=" + $_.Exception.Message)
}
Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue |
    Where-Object { $_.IPAddress -eq '192.168.137.1' } |
    ForEach-Object { Write-Output ("GW137=ifindex" + $_.InterfaceIndex) }
