; Inno Setup script. build.bat / CI compile it into dist\GoogleHomeWidget-Setup.exe.
#define AppName "Google Home Widget"
#define AppExe "GoogleHomeWidget.exe"
#define AppVersion "1.0.0"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"

[Setup]
AppId={{204897E6-1F1D-4CDB-A0A0-AF70D515A008}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Khlfnalvr
; Per-user install: no admin prompt, goes to %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=GoogleHomeWidget-Setup
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "startup"; Description: "Start with Windows"

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Registry]
; Same value the app's "Start with Windows" switch uses.
Root: HKCU; Subkey: "{#RunKey}"; ValueType: string; ValueName: "GoogleHomeWidget"; ValueData: """{app}\{#AppExe}"""; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "{#RunKey}"; ValueType: none; ValueName: "GoogleHomeWidget"; Tasks: not startup; Flags: deletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#AppExe}"; Flags: runhidden; RunOnceId: "StopApp"

[UninstallDelete]
; Settings and Google sign-in.
Type: filesandordirs; Name: "{userappdata}\GoogleHomeWidget"

[Code]
// Close a running copy so the exe can be replaced when updating.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/f /im {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
