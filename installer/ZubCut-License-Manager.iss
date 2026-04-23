; Inno Setup 6 — ZubCut License Manager Windows installer
; Prereq: python build_license_manager.py → dist\ZubCutLicenseManager\

#define MyAppName "ZubCut License Manager"
#define MyAppVersion "1.0"
#define MyAppPublisher "Local build"
#define MyAppExeName "ZubCutLicenseManager.exe"
#define MyAppURL "https://github.com/"

[Setup]
AppId={{3C91A74A-9F49-4A66-B3A6-6F353DF32E11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\ZubCutLicenseManager
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\output
OutputBaseFilename=ZubCut-License-Manager-Setup-{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern dark
WizardSmallImageFile=..\exe\zubcut_icon.png
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\ZubCutLicenseManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall shellexec

