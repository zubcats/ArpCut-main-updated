@echo off
:: One-click: restart hotspot services + open Mobile Hotspot settings
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0fix_mobile_hotspot_dhcp_auto.ps1\"\"'"
timeout /t 3 /nobreak >nul
start ms-settings:network-mobilehotspot
echo.
echo After UAC: services restart in the elevated window.
echo In Settings: turn Mobile hotspot OFF, wait 15 sec, ON, then reconnect PS5.
pause
