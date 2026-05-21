@echo off
title Lock Wi-Fi to 2.4 GHz (persistent)
cd /d "%~dp0"
echo Locks your PC on 2.4 GHz until you run Unlock-Wifi-To-5GHz.cmd.
echo Blocks 5 GHz networks and installs a watchdog so Windows cannot switch back.
echo Click Yes on the Administrator prompt.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0Lock-Wifi-To-2.4GHz.ps1\"\"'"
echo.
pause
