#define MyAppName "视饭AI:主机共享"
#define MyShortcutName "视饭AI主机共享"
#define MyAppVersion "0.5.0"
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
; v0.5: always show the install-directory page and allow the executable plus
; all three pairing fallback ports on RFC1918 private LAN ranges.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-入站"; Flags: runhidden; StatusMsg: "正在配置局域网访问权限..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-程序-入站 dir=in action=allow program=""{app}\{#MyAppExeName}"" remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-程序-出站 dir=out action=allow program=""{app}\{#MyAppExeName}"" remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-配对服务-入站 dir=in action=allow protocol=TCP localport=35999,24862,47891 remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-配对服务-出站 dir=out action=allow protocol=TCP remoteport=35999,24862,47891 remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-键鼠通道-入站 dir=in action=allow protocol=TCP localport=24861 remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-键鼠通道-出站 dir=out action=allow protocol=TCP remoteport=24861 remoteip=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 profile=any enable=yes"; Flags: runhidden
; Remove legacy rules after the new rules exist.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道"; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-程序-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务-出站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道-入站"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道-出站"; Flags: runhidden
