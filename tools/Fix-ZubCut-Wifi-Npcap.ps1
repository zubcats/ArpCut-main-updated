# Disable Npcap on disconnected adapters + repair ZubCut settings (run as Administrator).
$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Re-launching as Administrator...'
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

Write-Host '=== Disable Npcap on disconnected / APIPA-only adapters ==='
Get-NetAdapter | ForEach-Object {
    $name = $_.Name
    $st = $_.Status
    $bind = Get-NetAdapterBinding -Name $name -ComponentID 'INSECURE_NPCAP' -ErrorAction SilentlyContinue
    if (-not $bind -or -not $bind.Enabled) { return }
    if ($st -ne 'Up') {
        Disable-NetAdapterBinding -Name $name -ComponentID 'INSECURE_NPCAP'
        Write-Host "  Disabled Npcap on offline adapter: $name"
    }
}

Write-Host ''
Write-Host '=== Repair ZubCut settings (iface + PS5 last IP from ARP) ==='
$repo = Split-Path -Parent $PSScriptRoot
$py = @(
    'import sys, os',
    "sys.path.insert(0, os.path.join(r'$repo', 'src'))",
    'from tools.utils_gui import repair_settings',
    'repair_settings()',
    'print("zubcut.json repaired.")',
)
& py -c ($py -join '; ')
if ($LASTEXITCODE -ne 0) {
    & python -c ($py -join '; ')
}

Write-Host ''
Write-Host 'Done. Restart ZubCut, ARP scan, select PS5 (.248), try Lag.'
Write-Host 'Press Enter to close.'
Read-Host | Out-Null
