# Build output\ZubLock.zip for friends (installer inside). Used by CI.
$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
$Repo = Split-Path $Here -Parent
$OutDir = Join-Path $Repo 'output'
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$Ico = Join-Path $Here 'zublock.ico'
if (-not (Test-Path -LiteralPath $Ico)) {
    Copy-Item -LiteralPath (Join-Path $Repo 'exe\zubcut_shell.ico') -Destination $Ico -Force
}

$Names = @(
    'zublock_gui.py',
    'zublock_engine.py',
    'zublock_rules.py',
    'lock_ranges.txt',
    'zublock.ico',
    'Install-ZubLock.ps1',
    'Install-ZubLock.cmd',
    'Launch-ZubLock.ps1',
    'Launch-ZubLock.cmd',
    'Launch-ZubLock.vbs',
    'README.md'
)

$Stage = Join-Path ([IO.Path]::GetTempPath()) ('zublock-pack-' + [guid]::NewGuid().ToString('n'))
New-Item -ItemType Directory -Path $Stage -Force | Out-Null
try {
    foreach ($name in $Names) {
        $from = Join-Path $Here $name
        if (-not (Test-Path -LiteralPath $from)) { throw "Missing $name" }
        Copy-Item -LiteralPath $from -Destination (Join-Path $Stage $name) -Force
    }
    $Zip = Join-Path $OutDir 'ZubLock.zip'
    if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force }
    Compress-Archive -Path (Join-Path $Stage '*') -DestinationPath $Zip
    Write-Host "Wrote $Zip"
} finally {
    Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
}
