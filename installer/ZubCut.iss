; Inno Setup 6 — ZubCut Windows installer
; Prereq: python build.py → dist\ZubCut.exe

#define MyAppName "ZubCut"
#define MyAppVersion "1.29"
#define MyAppPublisher "Local build"
#define MyAppExeName "ZubCut.exe"
#define MyAppURL "https://github.com/"
#define NpcapInstallerName "npcap-1.87.exe"

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
OutputBaseFilename=ZubCut-Setup-{#MyAppVersion}
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
; Bundle Npcap installer with setup. Place this file at installer\npcap-1.87.exe before compiling.
Source: "..\installer\{#NpcapInstallerName}"; DestDir: "{tmp}"; Flags: deleteafterinstall ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Install Npcap only when it is missing.
Filename: "{tmp}\{#NpcapInstallerName}"; Parameters: "/S"; Flags: waituntilterminated skipifdoesntexist; Check: ShouldInstallNpcap
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall shellexec

[Code]
function NpcapServiceInstalled: Boolean;
begin
  Result := RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\npcap');
end;

function NpcapInstallPathExists: Boolean;
var
  InstallPath: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM, 'SOFTWARE\Npcap', 'InstallPath', InstallPath) then
    Result := DirExists(InstallPath);
end;

function NpcapInstallerBundled: Boolean;
var
  InstallerPath: String;
begin
  InstallerPath := ExpandConstant('{tmp}\{#NpcapInstallerName}');
  Result := FileExists(InstallerPath);
  if not Result then
    Log('Bundled Npcap installer not found at ' + InstallerPath + '. Setup will skip Npcap installation.');
end;

function ShouldInstallNpcap: Boolean;
begin
  Result := (not NpcapServiceInstalled) and (not NpcapInstallPathExists) and NpcapInstallerBundled;
  if Result then
    Log('Npcap not detected. Installing bundled Npcap.');
end;
