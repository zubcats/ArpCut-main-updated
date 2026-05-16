@echo off
title ZubCut - Repair Mobile Hotspot
echo Requesting Administrator (required)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0repair_clumsy_hotspot.ps1\"\"'"
pause
