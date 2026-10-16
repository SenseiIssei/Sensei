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
;   iscc packaging\sensei.iss /DAppVersion=0.2.0 /DSourceExe=..\dist-app\sensei.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; Relative to this file, i.e. to packaging/ — so the defaults have to climb out
; of it. They read `dist-app\...` and resolved to `packaging\dist-app\...`,
; which exists nowhere. The release workflow passed an explicit `..\` path for
; SourceExe and nothing at all for SourceExeW, so the broken default was what
; got used and the Windows installer job failed on a missing file.
#ifndef SourceExe
  #define SourceExe "..\dist-app\sensei.exe"
#endif
#ifndef SourceExeW
  #define SourceExeW "..\dist-app\senseiw.exe"
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
; `sensei update` runs this installer silently while Sensei itself is running.
; Restart Manager closes it so its files can be replaced; the [Run] entry
; below starts it again afterwards.
CloseApplications=force
RestartApplications=no
; The PATH entry below takes effect in new terminals without signing out.
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start Sensei when I sign in (runs in the system tray)"; GroupDescription: "Startup"
Name: "wiretools"; Description: "Connect the AI tools already on this machine"; GroupDescription: "Setup"

[Files]
; Two binaries from one codebase, the `python.exe` / `pythonw.exe` convention.
; `sensei.exe` has a console and is what you type commands into; `senseiw.exe`
; has none and is what every shortcut points at, so nothing the user clicks
; ever puts a black rectangle on their desktop.
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "sensei.exe"; Flags: ignoreversion
Source: "{#SourceExeW}"; DestDir: "{app}"; DestName: "senseiw.exe"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Every shortcut is the windowed binary with no arguments, which defaults to the
; tray. A shortcut that opens a console and holds it is not what someone
; clicking "Sensei" wants, and a server with neither console nor icon can only
; be stopped in Task Manager.
Name: "{group}\{#AppName}"; Filename: "{app}\senseiw.exe"; WorkingDir: "{app}"
Name: "{group}\Sensei Dashboard"; Filename: "http://localhost:7000/app/"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\senseiw.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\senseiw.exe"; Parameters: "tray --no-browser"; WorkingDir: "{app}"; Tasks: startup

[Run]
; Wiring happens before the first launch so the tools are already routed when
; the server comes up. `--dry-run` is not offered here: the checkbox above is
; the consent, and `setup-tools --undo` is the way back.
;
; `--from-installer` respects an earlier "Disconnect everything" and an earlier
; per-tool disconnect: `sensei update` re-runs this installer silently with the
; tasks it remembers, and that must not undo a decision made since.
Filename: "{app}\sensei.exe"; Parameters: "setup-tools --from-installer"; WorkingDir: "{app}"; \
  StatusMsg: "Connecting your AI tools..."; Flags: runhidden waituntilterminated; Tasks: wiretools
; Unticked, the answer has to outlive the installer. The tray started below
; runs a background scan that connects newly found tools, and without this it
; connected all of them thirty seconds after being told not to. Before the tray
; starts, so there is no window in which it can. `--if-unset` keeps a later
; "Connect everything" from being overridden by an update.
Filename: "{app}\sensei.exe"; Parameters: "setup-tools --auto off --if-unset"; WorkingDir: "{app}"; \
  Flags: runhidden waituntilterminated; Tasks: not wiretools
Filename: "{app}\senseiw.exe"; WorkingDir: "{app}"; \
  Description: "Start Sensei now"; Flags: nowait postinstall skipifsilent
; A silent run is an update from `sensei update`: bring the tray back.
Filename: "{app}\senseiw.exe"; Parameters: "tray --no-browser"; WorkingDir: "{app}"; \
  Flags: nowait; Check: WizardSilent

[UninstallRun]
; A running tray holds senseiw.exe open, and Windows will not delete it.
Filename: "{sys}\taskkill.exe"; Parameters: "/IM senseiw.exe /F"; \
  RunOnceId: "StopTray"; Flags: runhidden waituntilterminated
; `sensei autostart on` writes a Run key the installer did not create.
Filename: "{app}\sensei.exe"; Parameters: "autostart off"; WorkingDir: "{app}"; \
  RunOnceId: "AutostartOff"; Flags: runhidden waituntilterminated
; Put the other tools back before removing the binary they point at. Runs first
; because after the files are gone there is nothing left to run it with.
; `--forget`: uninstalling is not a decision about any one tool, so a later
; reinstall should connect them again rather than remember them as refused.
Filename: "{app}\sensei.exe"; Parameters: "setup-tools --undo --forget"; WorkingDir: "{app}"; \
  RunOnceId: "UnwireTools"; Flags: runhidden waituntilterminated

[UninstallDelete]
; The installer does not create these; the program does, next to itself.
Type: filesandordirs; Name: "{app}\.sensei_cache"
Type: filesandordirs; Name: "{app}\.sensei_sessions"
Type: filesandordirs; Name: "{app}\.sensei_memory"
Type: files; Name: "{app}\.sensei_savings.db*"
Type: files; Name: "{app}\.sensei_audit.jsonl"
Type: dirifempty; Name: "{app}"

[Registry]
; `sensei` on PATH for this user, so `sensei doctor` and `sensei update` work in
; any new terminal. Per-user (HKCU) like everything else here; removed again by
; the [Code] below on uninstall.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
function NeedsAddPath(Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Paths) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Paths, Dir: string;
  P: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Paths) then
    exit;
  Dir := ExpandConstant('{app}');
  P := Pos(';' + Uppercase(Dir), Uppercase(Paths));
  if P > 0 then
  begin
    Delete(Paths, P, Length(Dir) + 1);
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Paths);
  end;
end;
