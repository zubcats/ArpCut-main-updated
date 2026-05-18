@echo off
title Switch WiFi to 2.4 GHz
cd /d "%~dp0"
echo Switches your PC from 5 GHz to 2.4 GHz (same Wi-Fi name).
echo Click Yes on the Administrator prompt.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0Switch-Wifi-To-2.4GHz.ps1\"\"'"
echo.
pause
