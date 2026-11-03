; OpenStructures per-user installer. Compile from the repository root.
; Public Firebase client configuration is included in the desktop build.
; The migration tool, .env files and Firebase Admin keys are never distributed.

#define MyAppName "Open//Structures"
#define MyAppVersion "0.8.10"
#define MyAppPublisher "Open//Structures"
#define MyAppExeName "OpenStructures.exe"
; Preserve the existing installed application identity for upgrades.
#define MyAppId "{{CFB760FC-A702-4F1E-864E-79088FEF3B6F}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/ShaikhAhmedAzad/OpenCivil
AppSupportURL=https://github.com/ShaikhAhmedAzad/OpenCivil/issues
AppUpdatesURL=https://github.com/ShaikhAhmedAzad/OpenCivil/releases
VersionInfoDescription=OpenStructures structural analysis
VersionInfoVersion=0.8.0.0
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\OpenStructures
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=no
AppMutex=Open//StructuresAppMutex
WizardStyle=modern
SolidCompression=yes
Compression=lzma2
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=OpenStructures_Setup_v{#MyAppVersion}
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=app\graphic\logo.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[InstallDelete]
; Only PyInstaller's managed runtime is replaced. This also removes older
; copied auth source/credential bundles during an in-place per-user upgrade.
; User projects and the separate user profile/session directory are untouched.
Type: filesandordirs; Name: "{app}\_internal"
; Older onedir layouts placed copied authentication data beside the executable.
Type: filesandordirs; Name: "{app}\auth"
Type: filesandordirs; Name: "{app}\app\auth"

[Files]
Source: "dist\OpenStructures\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs overwritereadonly

[Icons]
Name: "{autoprograms}\OpenStructures"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\OpenStructures"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\Uninstall OpenStructures"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch OpenStructures"; Flags: nowait postinstall skipifsilent
