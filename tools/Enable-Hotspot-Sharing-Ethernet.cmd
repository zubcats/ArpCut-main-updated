@echo off
title Enable hotspot sharing (Ethernet)
cd /d "%~dp0"
echo Turns on Internet Connection Sharing: Ethernet -> PS5 hotspot.
echo Hotspot should be ON first. Click Yes on Administrator.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0Enable-Hotspot-Sharing-Ethernet.ps1\"\"'"
echo.
pause
