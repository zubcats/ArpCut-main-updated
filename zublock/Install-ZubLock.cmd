@echo off
title ZubLock installer
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-ZubLock.ps1"
if errorlevel 1 pause
