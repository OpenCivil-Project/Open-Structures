; ====================================================================
; Open//Structures Installer (Safe Clean Reinstall - Works Without Admin)
; ====================================================================

#define MyAppName "Open//Structures"
#define MyAppVersion "0.7.81"
#define MyAppPublisher "Open//Structures"
#define MyAppExeName "OpenStructures.exe"
#define MyAppId "{{CFB760FC-A702-4F1E-864E-79088FEF3B6F}}"

; --------------------------------------------------------------------
; SETUP
; --------------------------------------------------------------------
[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\OpenStructures

UsePreviousAppDir=yes
CloseApplications=yes
AppMutex=Open//StructuresAppMutex

WizardStyle=modern
SolidCompression=yes
DisableProgramGroupPage=yes

OutputBaseFilename=OpenStructures_Setup_v{#MyAppVersion}

UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=E:\MetuFire\Open//Structures\app\graphic\logo.ico

; --------------------------------------------------------------------
; FILES
; --------------------------------------------------------------------
[Files]
Source: "E:\MetuFire\Open//Structures\app\dist\Open//Structures\*"; \
DestDir: "{app}"; \
Flags: ignoreversion recursesubdirs createallsubdirs overwritereadonly

; --------------------------------------------------------------------
; SHORTCUTS
; --------------------------------------------------------------------
[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\Uninstall Open//Structures"; Filename: "{uninstallexe}"

; --------------------------------------------------------------------
; RUN
; --------------------------------------------------------------------
[Run]
Filename: "{app}\{#MyAppExeName}"; \
Flags: nowait postinstall skipifsilent

; --------------------------------------------------------------------
; CLEAN REINSTALL LOGIC (SAFE)
; --------------------------------------------------------------------
[Code]

var
  PreviousInstallPath: string;
  PreviousUninstaller: string;

function GetPreviousInstallPath(): string;
begin
  if not RegQueryStringValue(HKLM,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1',
    'InstallLocation', Result) then
  begin
    RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1',
      'InstallLocation', Result);
  end;
end;

function GetPreviousUninstaller(): string;
begin
  if not RegQueryStringValue(HKLM,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1',
    'UninstallString', Result) then
  begin
    RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1',
      'UninstallString', Result);
  end;
end;

function InitializeSetup(): Boolean;
begin
  PreviousInstallPath := GetPreviousInstallPath();
  PreviousUninstaller := GetPreviousUninstaller();
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    if (PreviousInstallPath <> '') and
       (ExpandConstant('{app}') = PreviousInstallPath) then
    begin
      if PreviousUninstaller <> '' then
      begin
        if IsAdminLoggedOn or IsAdminInstallMode then
        begin
          MsgBox('Existing installation detected. Cleaning previous version...',
            mbInformation, MB_OK);

          Exec(RemoveQuotes(PreviousUninstaller),
               '/VERYSILENT /NORESTART',
               '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        end
        else
        begin
          MsgBox('Previous version detected, but no admin rights.'#13#10 +
                 'Continuing without uninstall (files will be overwritten).',
                 mbInformation, MB_OK);
        end;
      end;
    end;
  end;
end;