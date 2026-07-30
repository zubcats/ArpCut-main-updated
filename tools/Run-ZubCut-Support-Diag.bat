@echo off
setlocal EnableExtensions
title ZubCut Support Diagnostic

:: Standalone repo helper — not part of the installed ZubCut.exe product.
:: Elevate to Administrator (required for Npcap / WinDivert probes)
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting Administrator...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

cd /d "%~dp0\.."

echo.
echo === ZubCut Support Diagnostic (repo standalone) ===
echo Report will be saved to your Desktop and opened automatically.
echo.

where py >nul 2>&1
if not errorlevel 1 (
  py -3 tools\zubcut_support_diag.py %*
  set "RC=%ERRORLEVEL%"
) else (
  where python >nul 2>&1
  if not errorlevel 1 (
    python tools\zubcut_support_diag.py %*
    set "RC=%ERRORLEVEL%"
  ) else (
    echo.
    echo ERROR: Python 3 was not found.
    echo Install Python 3, or run tools\ZubCut-Quick-Network-Diag.ps1 in Admin PowerShell.
    echo.
    pause
    exit /b 1
  )
)

for /f "delims=" %%F in ('powershell -NoProfile -Command "Get-ChildItem -Path ([Environment]::GetFolderPath('Desktop')) -Filter 'ZubCut-Support-Diag-*.txt' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName"') do (
  echo.
  echo Opening: %%F
  start "" notepad "%%F"
)

echo.
echo Done. Screenshot the SUMMARY + Issues sections in Notepad.
echo.
pause
exit /b %RC%
