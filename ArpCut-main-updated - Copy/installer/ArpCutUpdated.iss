; Inno Setup 6 script — builds a Windows installer for "ArpCut Updated"
; (separate from stock ArpCut: different folder, AppData, uninstall entry).
;
; Prereq: run `python build.py` from the repo root so dist\ArpCutUpdated.exe exists.
; Then: Build → Compile in Inno IDE, or run installer\Build-Installer.bat

#define MyAppName "ArpCut Updated"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "Local build"
#define MyAppExeName "ArpCutUpdated.exe"
#define MyAppURL "https://github.com/Mvgnu/ArpCut"

[Setup]
AppId={{E4B9F5C2-8D3A-4F1E-9C7B-2A6D8E0F1A3C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\output
OutputBaseFilename=ArpCutUpdated-Setup-{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
