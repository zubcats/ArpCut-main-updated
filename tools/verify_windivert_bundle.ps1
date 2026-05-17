# Fail if WinDivert binaries are missing before Inno compile (CI / local release build).
$ErrorActionPreference = 'Stop'
$Root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { Get-Location }
$Dir = Join-Path $Root 'installer\windivert'
$required = @('WinDivert.dll', 'WinDivert64.sys')
$missing = @()
foreach ($name in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $Dir $name))) {
        $missing += $name
    }
}
if ($missing.Count -gt 0) {
    Write-Error @(
        "WinDivert bundle incomplete in $Dir (missing: $($missing -join ', '))."
        'Run: pwsh -File installer/fetch_windivert.ps1'
    )
}
Write-Host "WinDivert bundle OK: $Dir"
