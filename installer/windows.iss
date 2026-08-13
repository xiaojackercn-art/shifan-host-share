#define MyAppName "视饭AI:主机共享"
#define MyShortcutName "视饭AI主机共享"
#define MyAppVersion "0.6.0"
#define MyAppPublisher "视饭AI"
#define MyAppExeName "ShifanAI-HostShare.exe"

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
; v0.6 follows Deskflow's standard direction: secondary -> host.
; Keep previous v0.5 pairing fallback rules for upgrade compatibility, and add
; Deskflow's standard TCP 24800 server port.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-入站"; Flags: runhidden; StatusMsg: "正在配置局域网访问权限..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-程序-入站 dir=in action=allow program=""{app}\{#MyAppExeName}"" remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-程序-出站 dir=out action=allow program=""{app}\{#MyAppExeName}"" remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-配对服务-入站 dir=in action=allow protocol=TCP localport=35999,24862,47891 remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-配对服务-出站 dir=out action=allow protocol=TCP remoteport=35999,24862,47891 remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-Deskflow-入站 dir=in action=allow protocol=TCP localport=24800 remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-Deskflow-出站 dir=out action=allow protocol=TCP remoteport=24800 remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
; Legacy 24861 cleanup/replacement kept safe for old installs.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道"; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-Deskflow-出站"; Flags: runhidden
