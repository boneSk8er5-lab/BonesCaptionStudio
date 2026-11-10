; Bones Caption Studio - Windows installer (Inno Setup 6, free: https://jrsoftware.org/isinfo.php)
;
; Normally you don't run this yourself: "python release.py build all final" calls it for you
; when Inno Setup is installed, passing these values:
;   /DAppVersion=6.7.0  /DEdition=CPU  /DSourceDir=<built app folder>  /DOutputDir=<releases folder>
;   /DOutputName=BonesCaptionStudio_v6.7.0_Windows_x64_CPU_Setup   [/DSpan=1 when the app is over ~1.8 GB]
;
; The installer is per-user (no admin prompt), installs to %LOCALAPPDATA%\Programs\Bones Caption Studio,
; adds Start menu / optional desktop shortcuts and lets .bcsproj caption projects open with a double-click.
; Settings live in %APPDATA%\BonesCaptionStudio, so they survive updates and uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Edition
  #define Edition "CPU"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\BonesCaptionStudio"
#endif
#ifndef OutputDir
  #define OutputDir "..\installer_output"
#endif
#ifndef OutputName
  #define OutputName "BonesCaptionStudio_v" + AppVersion + "_" + Edition + "_Setup"
#endif

#define AppName "Bones Caption Studio"
#define AppExe "BonesCaptionStudio.exe"
#define ProgId "BonesCaptionStudio.Project"

[Setup]
; Keep this AppId the same forever - it is how Windows knows a new version replaces the old one.
AppId={{6B1E4C2A-9D3F-4B7E-A1C5-BC5CA9710001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} ({#Edition})
AppPublisher=boneSk8er5
AppPublisherURL=https://github.com/boneSk8er5-lab/BonesCaptionStudio
AppSupportURL=https://github.com/boneSk8er5-lab/BonesCaptionStudio/issues
AppUpdatesURL=https://github.com/boneSk8er5-lab/BonesCaptionStudio/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile=..\BCS.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} ({#Edition})
Compression=lzma2/normal
SolidCompression=no
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
#ifdef Span
; Too big for one GitHub file (2 GB limit): split into Setup.exe + Setup-1.bin, -2.bin... (keep them together).
DiskSpanning=yes
DiskSliceSize=1900000000
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "Open .bcsproj caption projects with {#AppName}"; GroupDescription: "File types:"

[InstallDelete]
; Remove files left over from an older version before copying the new ones (models/ is kept).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "portable.txt,data\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\models"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same keys the app's Help menu uses, so the app shows the association as switched on.
Root: HKCU; Subkey: "Software\Classes\.bcsproj"; ValueType: string; ValueName: ""; ValueData: "{#ProgId}"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "{#AppName} Project"; Flags: uninsdeletekey; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Whisper models the app downloaded after install (can be large).
Type: filesandordirs; Name: "{app}\models"
