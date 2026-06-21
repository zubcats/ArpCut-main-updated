@echo off
:: ZubCut support diagnostic — saves logs to Desktop for support tickets.
:: Optional: pass PS5 IP as first argument, e.g. Run-ZubCut-Support-Diag.cmd 192.168.1.165
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-ZubCut-Support-Diag.ps1" %*
