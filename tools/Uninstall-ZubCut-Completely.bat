@echo off
setlocal EnableExtensions
title ZubCut complete uninstall

:: Fully remove ZubCut (old sticky installs that show "Updates Disabled").
:: Right-click this file -> Run as administrator  (or double-click; it will elevate).

net session >nul 2>&1
if errorlevel 1 (
  echo Requesting Administrator...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

cd /d "%~dp0"

echo.
echo === ZubCut complete uninstall ===
echo This removes ZubCut programs, shortcuts, autostart, stray ZubCut.exe copies,
echo and client AppData settings. Npcap is NOT removed.
echo.
echo Control Panel accounts + signing key are KEPT by default.
echo To also wipe those, run: Uninstall-ZubCut-Completely.ps1 -WipeControlPanelData
echo.
echo After this finishes, install the NEW ZubCut setup, then open it from the Start Menu.
echo.
pause

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uninstall-ZubCut-Completely.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo Script exited with code %RC%.
) else (
  echo Uninstall script finished.
)
echo.
pause
exit /b %RC%
