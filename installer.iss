; Inno Setup script for Video Batch Downloader.
; Build with:  .\build.ps1 -Installer      (or: ISCC installer.iss)
; Requires dist\VideoBatchDownloader.exe to exist first.

#define AppName "Video Batch Downloader"
#define AppVersion "0.2.0"
#define AppPublisher "KavumaHakim"
#define AppURL "https://github.com/KavumaHakim/video-batch-downloader"
#define AppExe "VideoBatchDownloader.exe"

[Setup]
AppId={{8E2C4B71-5A3D-4F96-9C18-2B7D6E4A1F03}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}

; Per-user install: no admin prompt, and the app stays able to write its
; settings, history, log and downloaded FFmpeg beside the executable.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

OutputDir=dist
OutputBaseFilename=VideoBatchDownloader-{#AppVersion}-setup
SetupIconFile=assets\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Files the app creates next to itself. Downloads are not touched: they go to
; a folder under Videos by default, and anywhere the user chose otherwise.
Type: filesandordirs; Name: "{app}\ffmpeg"
Type: files; Name: "{app}\download.log"
Type: files; Name: "{app}\settings.json"
Type: files; Name: "{app}\download_history.json"
