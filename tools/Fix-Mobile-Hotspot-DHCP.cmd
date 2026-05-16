@echo off
title ZubCut - Fix PC Hotspot for PS5
echo.
echo 1. Turn ON Mobile hotspot in Settings FIRST
echo 2. Click Yes on the Administrator prompt
echo 3. Window closes when done - read SUCCESS or ERROR
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0enable_hotspot_ics_now.ps1\"\"'"
echo.
if exist "%~dp0_enable_ics_result.txt" type "%~dp0_enable_ics_result.txt"
echo.
echo Done. Close any other blank PowerShell windows (old stuck runs).
timeout /t 8
