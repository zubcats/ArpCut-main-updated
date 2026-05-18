@echo off
title ZubCut - Full Mobile Hotspot Repair
echo.
echo 1. QUIT ZubCut completely before running this.
echo 2. Click Yes when Windows asks for Administrator.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0_hotspot_full_repair.ps1\"\"'"
echo.
pause
