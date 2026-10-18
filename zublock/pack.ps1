# Build output\ZubLock.zip with a single installer. Used by CI (Inno Setup exe).
$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
$Repo = Split-Path $Here -Parent
$OutDir = Join-Path $Repo 'output'
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$Ico = Join-Path $Here 'zublock.ico'
if (-not (Test-Path -LiteralPath $Ico)) {
    Copy-Item -LiteralPath (Join-Path $Repo 'exe\zubcut_shell.ico') -Destination $Ico -Force
}

function Get-Iscc {
    $cands = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $cands) {
        if ($path -and (Test-Path -LiteralPath $path)) { return $path }
    }
    return $null
}

$Zip = Join-Path $OutDir 'ZubLock.zip'
if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force }

$iscc = Get-Iscc
if ($iscc) {
    $iss = Join-Path $Repo 'installer\ZubLock.iss'
    & $iscc $iss
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed: $LASTEXITCODE" }
    $setup = Join-Path $OutDir 'ZubLock-Setup.exe'
    if (-not (Test-Path -LiteralPath $setup)) { throw 'ISCC did not write output\ZubLock-Setup.exe' }
    Compress-Archive -Path $setup -DestinationPath $Zip
    Write-Host "Wrote $Zip (ZubLock-Setup.exe)"
    return
}

Write-Host 'Inno Setup not found; packing ZubLock-Setup.cmd zip'
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
$Files = Join-Path $Stage 'files'
New-Item -ItemType Directory -Path $Files -Force | Out-Null
try {
    foreach ($name in $Names) {
        $from = Join-Path $Here $name
        if (-not (Test-Path -LiteralPath $from)) { throw "Missing $name" }
        Copy-Item -LiteralPath $from -Destination (Join-Path $Files $name) -Force
    }
    Copy-Item -LiteralPath (Join-Path $Here 'ZubLock-Setup.cmd') -Destination (Join-Path $Stage 'ZubLock-Setup.cmd') -Force
    Compress-Archive -Path (Join-Path $Stage '*') -DestinationPath $Zip
    Write-Host "Wrote $Zip (ZubLock-Setup.cmd)"
} finally {
    Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
}
