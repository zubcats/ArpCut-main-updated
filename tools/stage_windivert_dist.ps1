# Copy installer\windivert binaries into dist\ZubCut\windivert (same layout as {app}\windivert).
$ErrorActionPreference = 'Stop'
$Root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { Get-Location }
& (Join-Path $Root 'tools\verify_windivert_bundle.ps1')
$Src = Join-Path $Root 'installer\windivert'
$Dest = Join-Path (Join-Path $Root 'dist') 'ZubCut\windivert'
New-Item -ItemType Directory -Path $Dest -Force | Out-Null
foreach ($name in @('WinDivert.dll', 'WinDivert64.sys', 'WinDivert-LICENSE.txt')) {
    $from = Join-Path $Src $name
    if (Test-Path -LiteralPath $from) {
        Copy-Item -LiteralPath $from -Destination (Join-Path $Dest $name) -Force
    }
}
Write-Host "Staged WinDivert to $Dest"
