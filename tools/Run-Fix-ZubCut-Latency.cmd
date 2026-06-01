@echo off
:: Self-elevate once (UAC). Fixes Intel I219-LM settings Driver Easy resets.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0Fix-ZubCut-Ethernet-Latency.ps1\"\"' -Wait"
pause
