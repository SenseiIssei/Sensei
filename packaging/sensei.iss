; Windows installer for Sensei.
;
; The portable .exe is fine for someone who wants a portable .exe. Everyone else
; expects an installer: something that puts the program somewhere sensible, adds
; a Start-menu entry, offers to start with Windows, and uninstalls cleanly.
;
; Two choices worth writing down.
;
; It installs per-user, into %LOCALAPPDATA%, and asks for no administrator
; rights. Sensei listens on loopback and edits files in the user's own home
; directory; nothing it does needs the machine. Requesting elevation for that
; would be asking for a privilege in order not to use it.
;
; The uninstaller runs `setup-tools --undo` first. Sensei writes its address
; into other programs' configuration, and leaving those pointing at a gateway
; that no longer exists would break Claude Code, Cursor and the rest with a
; "connection refused" that never mentions Sensei.
;
;   iscc packaging\sensei.iss /DAppVersion=0.1.7 /DSourceExe=dist-app\sensei.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceExe
  #define SourceExe "dist-app\sensei.exe"
#endif

#define AppName "Sensei"
#define AppPublisher "SenseiIssei"
#define AppUrl "https://github.com/SenseiIssei/Sensei"

[Setup]
AppId={{8F3B1C42-5A7E-4D9E-9C21-6B0E7A4D2F18}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputBaseFilename=sensei-setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user: nothing here needs the machine, so nothing here asks for it.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\sensei.exe
SetupIconFile=sensei.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start Sensei when I sign in (runs in the system tray)"; GroupDescription: "Startup"
Name: "wiretools"; Description: "Connect the AI tools already on this machine"; GroupDescription: "Setup"

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "sensei.exe"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; The Start-menu entry runs the tray, not the bare server: a shortcut that opens
; a console window and holds it is not what someone clicking "Sensei" wants.
Name: "{group}\{#AppName}"; Filename: "{app}\sensei.exe"; Parameters: "tray"; WorkingDir: "{app}"
Name: "{group}\Sensei Dashboard"; Filename: "http://localhost:7000/app/"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\sensei.exe"; Parameters: "tray"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\sensei.exe"; Parameters: "tray --no-browser"; WorkingDir: "{app}"; Tasks: startup

[Run]
; Wiring happens before the first launch so the tools are already routed when
; the server comes up. `--dry-run` is not offered here: the checkbox above is
; the consent, and `setup-tools --undo` is the way back.
Filename: "{app}\sensei.exe"; Parameters: "setup-tools"; WorkingDir: "{app}"; \
  StatusMsg: "Connecting your AI tools..."; Flags: runhidden waituntilterminated; Tasks: wiretools
Filename: "{app}\sensei.exe"; Parameters: "tray"; WorkingDir: "{app}"; \
  Description: "Start Sensei now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Put the other tools back before removing the binary they point at. Runs first
; because after the files are gone there is nothing left to run it with.
Filename: "{app}\sensei.exe"; Parameters: "setup-tools --undo"; WorkingDir: "{app}"; \
  RunOnceId: "UnwireTools"; Flags: runhidden waituntilterminated

[UninstallDelete]
; The installer does not create these; the program does, next to itself.
Type: filesandordirs; Name: "{app}\.sensei_cache"
Type: filesandordirs; Name: "{app}\.sensei_sessions"
Type: filesandordirs; Name: "{app}\.sensei_memory"
Type: files; Name: "{app}\.sensei_savings.db*"
Type: files; Name: "{app}\.sensei_audit.jsonl"
Type: dirifempty; Name: "{app}"
