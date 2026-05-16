$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot '_hotspot_fix_result.txt'
function Log([string]$m) { $m | Tee-Object -FilePath $log -Append }

function Wait-AsyncOp($op, [string]$label) {
    $deadline = (Get-Date).AddSeconds(30)
    while ($op.Status -eq 'Started') {
        if ((Get-Date) -gt $deadline) { throw "$label timed out" }
        Start-Sleep -Milliseconds 200
    }
    if ($op.Status -eq 'Error') { throw "$label failed: $($op.ErrorCode)" }
    return $op.GetResults()
}

try {
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if (-not $profile) { throw 'No internet connection profile — connect PC Wi-Fi to router first.' }
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
    Log "Hotspot state before: $($mgr.TetheringOperationalState)"
    if ($mgr.TetheringOperationalState -ne 'On') {
        $r = Wait-AsyncOp ($mgr.StartTetheringAsync()) 'StartTethering'
        Log "StartTethering: $r"
    } else {
        Log 'Hotspot already on'
    }
    Start-Sleep -Seconds 10
    $dhcp = Get-NetUDPEndpoint -LocalPort 67 -ErrorAction SilentlyContinue
    $gw = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq '192.168.137.1' } | Select-Object -First 1
    Log "FINAL dhcp67=$([bool]$dhcp) gw137=$([bool]$gw)"
    if (-not $dhcp) { exit 1 }
    exit 0
} catch {
    Log "ERROR: $($_.Exception.Message)"
    exit 1
}
