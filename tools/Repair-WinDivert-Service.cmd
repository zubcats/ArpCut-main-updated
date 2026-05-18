@echo off
title Repair WinDivert driver (Kill error code 3)
echo Fixes WinDivert when Kill says "cannot find the path specified (code 3)".
echo Click Yes on the Administrator prompt.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0_repair_windivert_service.ps1\"\"'"
echo.
pause
