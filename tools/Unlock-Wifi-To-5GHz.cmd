@echo off
title Restore Wi-Fi (unlock + hotspot off + 5 GHz)
cd /d "%~dp0"
echo Full recovery: removes 2.4 lock, turns OFF mobile hotspot, reconnects PC to 5 GHz.
echo Click Yes on the Administrator prompt.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0Unlock-Wifi-To-5GHz.ps1\"\"'"
echo.
pause
