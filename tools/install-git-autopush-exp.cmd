@echo off
setlocal
cd /d "%~dp0\.."
git config core.hooksPath .githooks
if errorlevel 1 (
  echo Failed: run this from a Git clone of the repo.
  exit /b 1
)
echo OK: core.hooksPath=.githooks — commits on branch experimental will auto-push to origin/experimental.
echo On Mac/Linux, if the hook is ignored, run: chmod +x .githooks/post-commit
exit /b 0
