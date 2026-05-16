@echo off
title Restore WLAN AutoConfig (Wi-Fi)
echo Restores WLAN AutoConfig after an old ZubCut build broke Wi-Fi.
echo Click Yes on the Administrator prompt.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0Restore-Wlan-AutoConfig.ps1\"\"'"
echo.
pause
