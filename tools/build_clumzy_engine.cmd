@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

rem %ProgramFiles(x86)% must be captured outside parentheses or cmd splits on (x86).
set "PF86=%ProgramFiles(x86)%"
set "VSWHERE=%PF86%\Microsoft Visual Studio\Installer\vswhere.exe"

where cl >nul 2>&1
if errorlevel 1 (
  set "VCVARS="
  if exist "!VSWHERE!" (
    for /f "usebackq delims=" %%i in (`"!VSWHERE!" -latest -property installationPath`) do (
      if exist "%%i\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%i\VC\Auxiliary\Build\vcvars64.bat"
    )
  )
  if not defined VCVARS (
    for %%Y in (2022 2025 18) do (
      for %%E in (Enterprise Professional Community BuildTools) do (
        if exist "%ProgramFiles%\Microsoft Visual Studio\%%Y\%%E\VC\Auxiliary\Build\vcvars64.bat" (
          set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\%%Y\%%E\VC\Auxiliary\Build\vcvars64.bat"
        )
      )
    )
  )
  if not defined VCVARS (
    echo vcvars64.bat not found. Install Visual Studio C++ tools to build clumzy_engine.dll.
    exit /b 1
  )
  call "!VCVARS!" || exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ensure_windivert_sdk.ps1" || exit /b 1

set "SDK=%CD%\native\clumzy_engine\windivert-sdk"
if not exist "%SDK%\include\windivert.h" (
  echo Missing WinDivert SDK headers at %SDK%\include
  exit /b 1
)
if not exist "%SDK%\lib\WinDivert.lib" (
  echo Missing WinDivert.lib at %SDK%\lib
  exit /b 1
)

set "OUTDIR=%CD%\native\clumzy_engine\out"
if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
mkdir "%OUTDIR%\obj" || exit /b 1

cl /nologo /c /O2 /DNDEBUG /DX64 /DCLUMZY_ENGINE_ONLY /D_CRT_SECURE_NO_WARNINGS /wd4214 /std:c11 ^
  /I native\clumzy_engine\include ^
  /I native\clumzy_engine\src ^
  /I "%SDK%\include" ^
  /Fo%OUTDIR%\obj\ ^
  native\clumzy_engine\iup_stub.c ^
  native\clumzy_engine\src\bandwidth.c native\clumzy_engine\src\clumzy_api.c native\clumzy_engine\src\disconnect.c ^
  native\clumzy_engine\src\divert.c native\clumzy_engine\src\drop.c native\clumzy_engine\src\duplicate.c ^
  native\clumzy_engine\src\elevate.c native\clumzy_engine\src\lag.c native\clumzy_engine\src\modules.c ^
  native\clumzy_engine\src\ood.c native\clumzy_engine\src\packet.c native\clumzy_engine\src\reset.c ^
  native\clumzy_engine\src\tamper.c native\clumzy_engine\src\throttle.c native\clumzy_engine\src\utils.c || exit /b 1

link /nologo /DLL /SAFESEH:NO /OUT:%OUTDIR%\clumzy_engine.dll ^
  %OUTDIR%\obj\*.obj ^
  /LIBPATH:"%SDK%\lib" ^
  WinDivert.lib winmm.lib ws2_32.lib kernel32.lib user32.lib advapi32.lib shell32.lib || exit /b 1

echo Built %OUTDIR%\clumzy_engine.dll
dir "%OUTDIR%\clumzy_engine.dll"
exit /b 0
