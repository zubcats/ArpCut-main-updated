@echo off
title ZubLock installer
cd /d "%~dp0"
if exist "%~dp0files\Install-ZubLock.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0files\Install-ZubLock.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-ZubLock.ps1"
)
if errorlevel 1 pause
