WinDivert (64-bit) for the Clumsy mode optional installer task (WinDivert 2.x, LGPL).

WinDivert 2.x does not use an .inf in the release zip: ship WinDivert.dll + WinDivert64.sys
(next to ZubCut in {app}\windivert\). The driver loads when a program opens it (admin).

CI: GitHub Actions runs installer\fetch_windivert.ps1 before ISCC so this folder contains
the real binaries for that build.

Local Inno compile: from repo root, run:
  pwsh -File installer\fetch_windivert.ps1
then compile ZubCut.iss.

If you skip the fetch step, only README.txt may be here and the installer will not bundle WinDivert.
