. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
. (Join-Path $PSScriptRoot '_winrt_await.ps1')
$m = Get-TetheringManager
if (-not $m) { Write-Host 'No tethering manager'; exit 1 }
Write-Host "State: $($m.TetheringOperationalState)"
Write-Host "SSID prefix: $($m.Configuration.SsidPrefix)"
try {
    $apc = $m.GetCurrentAccessPointConfiguration()
    Write-Host "AP SSID: $($apc.Ssid)"
} catch {}
Write-Host "Band: $(Get-MobileHotspotApBandLabel $m)"
try {
    $cs = $m.GetTetheringClients()
    Write-Host "Clients: $($cs.Count)"
    foreach ($c in $cs) { Write-Host "  $($c.MacAddress)  $($c.HostName)" }
} catch { Write-Host "Clients error: $_" }
Get-NetNeighbor | Where-Object { $_.IPAddress -like '192.168.137.*' -and $_.State -ne 'Unreachable' } |
    Format-Table IPAddress, LinkLayerAddress, State -AutoSize
