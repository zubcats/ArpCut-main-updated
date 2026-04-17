; Inno Setup 6 — ZubCut Windows installer
; Prereq: python build.py → dist\ZubCut\ (onedir — copy full folder into {app})
;
; The same compiled setup .exe is used for:
;   - First install (GitHub / manual download), and
;   - In-app updates (downloaded installer).
; WizardStyle and images below apply to both.

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
; modern + built-in dark style (Inno 6+). Use "modern dynamic" instead to follow Windows light/dark.
WizardStyle=modern dark
; Top-right logo (modern wizard ~120×120; Inno scales PNG). For a custom left panel use WizardImageFile (~164×314).
WizardSmallImageFile=..\exe\zubcut_icon.png
; Setup/uninstall file icon (.ico only). Uncomment after adding installer\branding\setup.ico (e.g. convert from zubcut_icon.png).
;SetupIconFile=branding\setup.ico
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
; Allow Restart Manager to close ZubCut so the old one-file EXE is not left in place beside the new onedir layout.
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
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
