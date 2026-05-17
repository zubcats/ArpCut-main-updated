WinDivert (64-bit) for the Clumsy mode installer task (WinDivert 2.x, LGPL).

When the user selects "Clumsy mode" in setup, ZubCut installs:
  {app}\windivert\WinDivert.dll
  {app}\windivert\WinDivert64.sys
and writes clumsy_mode_bundle.flag (only if both files are present).

WinDivert 2.x does not use pnputil. The driver loads when ZubCut runs as Administrator.

Before compiling ZubCut.iss (required — compile fails if DLL/SYS are missing):
  pwsh -File installer\fetch_windivert.ps1
  pwsh -File tools\verify_windivert_bundle.ps1

CI runs fetch + verify automatically before Inno Setup.
