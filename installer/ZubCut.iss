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
Name: "clumsymode"; Description: "Clumsy mode (WinDivert for PC Mobile Hotspot lag)"; GroupDescription: "Optional:"; Flags: checked

; Replace the whole onedir payload on upgrade (avoids stale PyInstaller files beside new builds).
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bundle Npcap installer with setup. Place this file at installer\npcap-1.87.exe before compiling.
Source: "..\installer\{#NpcapInstallerName}"; DestDir: "{tmp}"; Flags: deleteafterinstall ignoreversion skipifsourcedoesntexist
; WinDivert 2.x: run installer\fetch_windivert.ps1 before compile (required — ISCC fails if missing).
; Installed only when the Clumsy mode task is selected (checked by default).
Source: "..\installer\windivert\WinDivert.dll"; DestDir: "{app}\windivert"; Tasks: clumsymode; Flags: ignoreversion
Source: "..\installer\windivert\WinDivert64.sys"; DestDir: "{app}\windivert"; Tasks: clumsymode; Flags: ignoreversion
Source: "..\installer\windivert\WinDivert-LICENSE.txt"; DestDir: "{app}\windivert"; Tasks: clumsymode; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\tools\repair_clumsy_hotspot.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\tools\Repair-Clumsy-Hotspot.cmd"; DestDir: "{app}\tools"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall shellexec

[Code]
function WinPcapUninstallString(var UninstallString: String): Boolean;
begin
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst', 'UninstallString', UninstallString);
  if not Result then
    Result := RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst', 'UninstallString', UninstallString);
  if not Result then
    Result := RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst', 'UninstallString', UninstallString);
end;

function SplitCommand(const FullCmd: String; var ExePath: String; var Params: String): Boolean;
var
  S: String;
  P: Integer;
begin
  Result := False;
  ExePath := '';
  Params := '';
  S := Trim(FullCmd);
  if S = '' then
    Exit;
  if S[1] = '"' then
  begin
    Delete(S, 1, 1);
    P := Pos('"', S);
    if P <= 0 then
      Exit;
    ExePath := Copy(S, 1, P - 1);
    Params := Trim(Copy(S, P + 1, MaxInt));
    Result := ExePath <> '';
    Exit;
  end;
  P := Pos(' ', S);
  if P > 0 then
  begin
    ExePath := Copy(S, 1, P - 1);
    Params := Trim(Copy(S, P + 1, MaxInt));
  end
  else
    ExePath := S;
  Result := ExePath <> '';
end;

procedure MsgWinPcapManualUninstallNeeded(const Detail: String);
begin
  MsgBox(
    'WinPcap could not be removed automatically.' + #13#10 + #13#10 +
    'WinPcap installs a packet capture driver that conflicts with Npcap, which ZubCut requires.' + #13#10 + #13#10 +
    'Please uninstall WinPcap manually from Apps & Features (or Programs and Features), then run this installer again.' + #13#10 + #13#10 +
    'Contact your administrator if you need help.' + #13#10 + #13#10 +
    Detail,
    mbError,
    MB_OK);
end;

procedure UninstallWinPcapIfPresent();
var
  UninstallString: String;
  UninstallExe: String;
  UninstallParams: String;
  ResultCode: Integer;
begin
  if not WinPcapUninstallString(UninstallString) then
    Exit;

  if not SplitCommand(UninstallString, UninstallExe, UninstallParams) then
  begin
    Log('WinPcap uninstall string is invalid: ' + UninstallString);
    MsgWinPcapManualUninstallNeeded('Reason: could not read the WinPcap uninstall path from the registry.');
    Exit;
  end;

  if Pos('/S', Uppercase(UninstallParams)) = 0 then
    UninstallParams := Trim(UninstallParams + ' /S');

  Log('WinPcap detected. Running silent uninstall: ' + UninstallExe + ' ' + UninstallParams);
  if not Exec(UninstallExe, UninstallParams, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Log('Failed to launch WinPcap uninstaller.');
    MsgWinPcapManualUninstallNeeded('Reason: the uninstall program could not be started.');
  end
  else
  begin
    Log('WinPcap uninstall finished with exit code ' + IntToStr(ResultCode) + '.');
    // 3010/1641/3017 = success but reboot may be required (do not treat as hard failure).
    if (ResultCode <> 0) and (ResultCode <> 3010) and (ResultCode <> 1641) and (ResultCode <> 3017) then
      MsgWinPcapManualUninstallNeeded('Reason: uninstall exited with code ' + IntToStr(ResultCode) + '.');
  end;
end;

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

procedure InstallNpcapIfMissing();
var
  InstallerPath: String;
  ResultCode: Integer;
begin
  if not ShouldInstallNpcap() then
    Exit;
  InstallerPath := ExpandConstant('{tmp}\{#NpcapInstallerName}');
  if not Exec(InstallerPath, '/S', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log('Failed to launch bundled Npcap installer.')
  else
    Log('Npcap installer finished with exit code ' + IntToStr(ResultCode) + '.');
end;

function WinDivertDllInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\windivert\WinDivert.dll'));
end;

function WinDivertSysInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\windivert\WinDivert64.sys'));
end;

function ClumsyModeTaskSelected: Boolean;
begin
  Result := WizardIsTaskSelected('clumsymode');
end;

procedure EnsureWinDivertInstalledForClumsy();
begin
  if not ClumsyModeTaskSelected() then
    Exit;
  if WinDivertDllInstalled() and WinDivertSysInstalled() then
  begin
    Log('WinDivert installed under {app}\windivert');
    Exit;
  end;
  Log('Clumsy mode selected but WinDivert files missing under {app}\windivert');
  MsgBox(
    'Clumsy mode was selected, but WinDivert could not be installed.' + #13#10 + #13#10 +
    'Expected under:' + #13#10 +
    '  ' + ExpandConstant('{app}\windivert\') + #13#10 + #13#10 +
    'Re-download ZubCut from the official build, keep "Clumsy mode" checked, and run setup as Administrator.',
    mbError,
    MB_OK);
end;

procedure MaybeWriteClumsyBundleFlag();
var
  FlagPath: String;
begin
  if not ClumsyModeTaskSelected() then
    Exit;
  if not (WinDivertDllInstalled() and WinDivertSysInstalled()) then
  begin
    Log('Skipping clumsy_mode_bundle.flag — WinDivert not installed.');
    Exit;
  end;
  FlagPath := ExpandConstant('{app}\clumsy_mode_bundle.flag');
  SaveStringToFile(FlagPath, '1', False);
  Log('Wrote Clumsy bundle marker: ' + FlagPath);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    UninstallWinPcapIfPresent();
    InstallNpcapIfMissing();
    EnsureWinDivertInstalledForClumsy();
    MaybeWriteClumsyBundleFlag();
  end;
end;
