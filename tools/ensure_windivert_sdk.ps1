# Fetch WinDivert 2.2.2 headers + import lib for compiling clumzy_engine.dll.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Sdk = Join-Path $Root 'native\clumzy_engine\windivert-sdk'
$Hdr = Join-Path $Sdk 'include\windivert.h'
$Lib = Join-Path $Sdk 'lib\WinDivert.lib'
if ((Test-Path -LiteralPath $Hdr) -and (Test-Path -LiteralPath $Lib)) {
    Write-Host "WinDivert SDK already present: $Sdk"
    exit 0
}

$Version = '2.2.2'
$Url = "https://github.com/basil00/WinDivert/releases/download/v$Version/WinDivert-$Version-A.zip"
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("windivert-sdk-" + [Guid]::NewGuid().ToString('n'))
New-Item -ItemType Directory -Path $Tmp -Force | Out-Null
try {
    $Zip = Join-Path $Tmp 'WinDivert.zip'
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
    Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
    $Include = Get-ChildItem -Path $Tmp -Recurse -File -Filter 'windivert.h' | Select-Object -First 1
    $X64 = Get-ChildItem -Path $Tmp -Recurse -Directory -Filter 'x64' | Select-Object -First 1
    if (-not $Include) { throw 'windivert.h not found in WinDivert zip' }
    if (-not $X64) { throw 'x64 folder not found in WinDivert zip' }
    $LibSrc = Join-Path $X64.FullName 'WinDivert.lib'
    if (-not (Test-Path -LiteralPath $LibSrc)) { throw 'WinDivert.lib not found in x64 folder' }
    New-Item -ItemType Directory -Path (Join-Path $Sdk 'include') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $Sdk 'lib') -Force | Out-Null
    Copy-Item -LiteralPath $Include.FullName -Destination $Hdr -Force
    $Def = Join-Path $Include.DirectoryName 'windivert.dll.def'
    if (Test-Path -LiteralPath $Def) {
        Copy-Item -LiteralPath $Def -Destination (Join-Path $Sdk 'include\windivert.dll.def') -Force
    }
    Copy-Item -LiteralPath $LibSrc -Destination $Lib -Force
    Write-Host "WinDivert SDK staged at $Sdk"
}
finally {
    Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
