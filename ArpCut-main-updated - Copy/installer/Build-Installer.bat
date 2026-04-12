@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo === Build ArpCutUpdated.exe (PyInstaller^) ===
python build.py
if errorlevel 1 (
  echo.
  echo build.py failed. Use Python 3.8+ on PATH, install deps: pip install -r requirements.txt pyinstaller pillow
  exit /b 1
)

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo.
  echo Inno Setup 6 not found. Install from: https://jrsoftware.org/isdl.php
  echo After installing, run this batch file again.
  exit /b 1
)

echo.
echo === Compile installer (Inno Setup^) ===
"%ISCC%" "%~dp0ArpCutUpdated.iss"
if errorlevel 1 exit /b 1

echo.
echo Done. Open the "output" folder for ArpCutUpdated-Setup-*.exe
endlocal
