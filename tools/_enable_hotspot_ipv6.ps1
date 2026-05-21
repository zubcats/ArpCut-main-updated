# Re-enable IPv6 on hotspot NIC (disabling it can block phone/PS5 association).
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}
$ap = Get-NetAdapter -EA SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Hosted' -or $_.Name -match 'Local Area Connection\*')
} | Select-Object -First 1
if ($ap) {
    Enable-NetAdapterBinding -Name $ap.Name -ComponentID ms_tcpip6 -EA SilentlyContinue
    Write-Host "IPv6 enabled on $($ap.Name)"
}
