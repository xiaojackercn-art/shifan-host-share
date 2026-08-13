#define MyAppName "视饭AI:主机共享"
#define MyShortcutName "视饭AI主机共享"
#define MyAppVersion "0.8.0"
#define MyAppPublisher "视饭AI"
#define MyAppExeName "ShifanAI-HostShare.exe"
#define DeskflowExe "engine\Deskflow\deskflow-core.exe"

[Setup]
AppId={{EA552F5F-1F24-4EAE-9FFB-BA1418C5E911}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ShifanAI Host Share
DefaultGroupName={#MyShortcutName}
OutputDir=..\release
OutputBaseFilename=ShifanAI-HostShare-Setup-x64
SetupIconFile=..\assets\AI.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableDirPage=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\ShifanAI-HostShare\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyShortcutName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyShortcutName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[Run]
; v0.8: the ShifanAI process owns the LAN-facing 0.0.0.0:24800 listener.
; Deskflow server is loopback-only on 127.0.0.1:24810.  Therefore the main
; executable itself needs the inbound LAN exception; deskflow-core only needs
; outbound LAN access when this computer is the secondary/client.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-主程序-入站"; Flags: runhidden; StatusMsg: "正在配置视饭AI主机共享局域网权限..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-主程序-入站 dir=in action=allow program=""{app}\{#MyAppExeName}"" protocol=TCP localport=24800 remoteip=LocalSubnet profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-主程序-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-主程序-出站 dir=out action=allow program=""{app}\{#MyAppExeName}"" remoteip=LocalSubnet profile=any enable=yes"; Flags: runhidden

Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow程序-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-Deskflow程序-入站 dir=in action=allow program=""{app}\{#DeskflowExe}"" remoteip=LocalSubnet profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow程序-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-Deskflow程序-出站 dir=out action=allow program=""{app}\{#DeskflowExe}"" remoteip=LocalSubnet profile=any enable=yes"; Flags: runhidden

Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-Deskflow-入站 dir=in action=allow protocol=TCP localport=24800 remoteip=LocalSubnet profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-Deskflow-出站 dir=out action=allow protocol=TCP remoteport=24800 remoteip=LocalSubnet profile=any enable=yes"; Flags: runhidden

; Remove obsolete v0.1-v0.7 custom pairing and old keyboard-channel rules.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道-出站"; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-主程序-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-主程序-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow程序-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow程序-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow-出站"; Flags: runhidden
