# Download WinDivert (LGPL) x64 binaries into installer\windivert for Inno Setup.
# Run before ISCC locally or rely on CI. See installer\windivert\README.txt
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Dest = Join-Path (Join-Path $Root 'installer') 'windivert'
$Version = '2.2.2'
$Url = "https://github.com/basil00/WinDivert/releases/download/v$Version/WinDivert-$Version-A.zip"
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("windivert-fetch-" + [Guid]::NewGuid().ToString('n'))
New-Item -ItemType Directory -Path $Tmp -Force | Out-Null
try {
    $Zip = Join-Path $Tmp 'WinDivert.zip'
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
    Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
    $X64 = Get-ChildItem -Path $Tmp -Recurse -Directory -Filter 'x64' | Select-Object -First 1
    if (-not $X64) { throw 'WinDivert zip: x64 folder not found' }
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    foreach ($name in @('WinDivert.dll', 'WinDivert64.sys')) {
        $src = Join-Path $X64.FullName $name
        if (-not (Test-Path -LiteralPath $src)) { throw "Missing $name in WinDivert x64 package" }
        Copy-Item -LiteralPath $src -Destination (Join-Path $Dest $name) -Force
    }
    $lic = Get-ChildItem -Path $Tmp -Recurse -File -Filter 'LICENSE' | Select-Object -First 1
    if ($lic) {
        Copy-Item -LiteralPath $lic.FullName -Destination (Join-Path $Dest 'WinDivert-LICENSE.txt') -Force
    }
    Write-Host "WinDivert $Version x64 copied to $Dest"
}
finally {
    Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
