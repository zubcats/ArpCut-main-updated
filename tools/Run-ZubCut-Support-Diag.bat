@echo off
setlocal EnableExtensions
title ZubCut Support Diagnostic

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
echo === ZubCut Support Diagnostic ===
echo Report will be saved to your Desktop and opened automatically.
echo.

:: Prefer installed ZubCut.exe --support-diag (after update)
set "ZUBCUT_EXE="
if exist "%ProgramFiles%\ZubCut\ZubCut.exe" set "ZUBCUT_EXE=%ProgramFiles%\ZubCut\ZubCut.exe"
if not defined ZUBCUT_EXE if exist "%LocalAppData%\ZubCut\ZubCut.exe" set "ZUBCUT_EXE=%LocalAppData%\ZubCut\ZubCut.exe"

if defined ZUBCUT_EXE (
  echo Using: %ZUBCUT_EXE% --support-diag
  "%ZUBCUT_EXE%" --support-diag %*
  set "RC=%ERRORLEVEL%"
) else (
  echo ZubCut.exe not found — running Python diagnostic from this repo.
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
      echo ERROR: Neither ZubCut.exe nor Python was found.
      echo Install / update ZubCut, or install Python 3, then re-run this bat.
      echo.
      pause
      exit /b 1
    )
  )
)

:: Open newest Desktop report if the EXE path did not already
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
