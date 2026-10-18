; Inno Setup 6 - ZubLock (standalone; not part of ZubCut)
; Copies the small Tk app, then Install-ZubLock.ps1 fetches WinDivert / Python+Tk if needed.

#define MyAppName "ZubLock"
#define MyAppVersion "1.0.5"
#define MyAppPublisher "ZubOnTop"
#define MyAppURL "https://github.com/zubcats/ArpCut-main-updated"

[Setup]
AppId={{B6D1E8A4-2C70-4F19-9E5B-8A4C31D07F62}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\ZubLock
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
OutputDir=..\output
OutputBaseFilename=ZubLock-Setup
UninstallDisplayIcon={app}\zublock.ico
SetupIconFile=..\zublock\zublock.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern dark
WizardSmallImageFile=..\exe\zubcut_icon.png
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\zublock\zublock_gui.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\zublock_engine.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\zublock_rules.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\lock_ranges.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\zublock.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\zublock_taskbar.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\Install-ZubLock.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\Install-ZubLock.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\Launch-ZubLock.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\Launch-ZubLock.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\Launch-ZubLock.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zublock\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\Launch-ZubLock.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\zublock.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\Launch-ZubLock.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\zublock.ico"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\Install-ZubLock.ps1"""; WorkingDir: "{app}"; StatusMsg: "Downloading WinDivert and Python if needed..."; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\windivert"
