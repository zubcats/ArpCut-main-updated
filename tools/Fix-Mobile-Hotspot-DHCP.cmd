@echo off
title Fix PC Mobile Hotspot for PS5
echo.
echo This enables Internet Connection Sharing (DHCP) for your PC hotspot.
echo You MUST click Yes on the Administrator prompt.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0enable_hotspot_ics_now.ps1\"\"'"
echo.
if exist "%~dp0_enable_ics_result.txt" type "%~dp0_enable_ics_result.txt"
echo.
echo If SUCCESS above: reconnect PS5 to PC hotspot Wi-Fi.
echo If still failing: Settings -^> Mobile hotspot OFF 15 sec ON, then run this again.
echo.
pause
