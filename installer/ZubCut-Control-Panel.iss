; Inno Setup 6 — ZubCut Control Panel Windows installer
; Prereq: python build_control_panel.py → dist\ZubCutControlPanel\

#define MyAppName "ZubCut Control Panel"
#define MyAppVersion "1.0"
#define MyAppPublisher "ZubOnTop"
#define MyAppExeName "ZubCutControlPanel.exe"
#define MyAppURL "https://github.com/zubcats/ArpCut-main-updated"

[Setup]
AppId={{A8E2C41B-5D93-4F7A-9B12-3C6D8E0F2A94}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\ZubCut Control Panel
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\output
OutputBaseFilename=ZubCut-Control-Panel-Setup-{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern dark
WizardSmallImageFile=..\exe\zubcut_icon.png
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\ZubCutControlPanel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  LegacyLicenseManagerAppId = '{3C91A74A-9F49-4A66-B3A6-6F353DF32E11}';

function LegacyLicenseManagerUninstallKey(): String;
begin
  Result := 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\' + LegacyLicenseManagerAppId + '_is1';
end;

function LegacyLicenseManagerInstalled(): Boolean;
begin
  Result :=
    RegKeyExists(HKLM, LegacyLicenseManagerUninstallKey()) or
    RegKeyExists(HKCU, LegacyLicenseManagerUninstallKey());
end;

procedure RemoveLegacyLicenseManager();
var
  Uninst: String;
  ResultCode: Integer;
begin
  if RegQueryStringValue(HKLM, LegacyLicenseManagerUninstallKey(), 'UninstallString', Uninst) or
     RegQueryStringValue(HKCU, LegacyLicenseManagerUninstallKey(), 'UninstallString', Uninst) then
  begin
    Uninst := RemoveQuotes(Uninst);
    if Uninst <> '' then
      Exec(Uninst, '/SILENT', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssInstall) and LegacyLicenseManagerInstalled() then
    RemoveLegacyLicenseManager();
end;
