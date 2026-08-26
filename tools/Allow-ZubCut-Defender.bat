@echo off
setlocal EnableExtensions
title Allow ZubCut in Windows Defender

:: Run this BEFORE installing or opening ZubCut if Defender quarantines it.
:: Right-click -> Run as administrator

net session >nul 2>&1
if errorlevel 1 (
  echo Requesting Administrator...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

cd /d "%~dp0"

echo.
echo === Allow ZubCut in Windows Defender ===
echo This adds exclusions so Defender stops quarantining ZubCut.
echo Run this first, then install / open ZubCut.
echo.
pause

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Allow-ZubCut-Defender.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo Script exited with code %RC%.
) else (
  echo Done. Reinstall ZubCut if files are missing, then open it from Start.
)
echo.
pause
exit /b %RC%
