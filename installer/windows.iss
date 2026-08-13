#define MyAppName "视饭AI:主机共享"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "视饭AI"
#define MyAppExeName "ShifanAI-HostShare.exe"

[Setup]
AppId={{EA552F5F-1F24-4EAE-9FFB-BA1418C5E911}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ShifanAI Host Share
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=ShifanAI-HostShare-Setup-x64
SetupIconFile=..\assets\AI.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\ShifanAI-HostShare\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务"; Flags: runhidden; StatusMsg: "正在更新防火墙规则..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-配对服务 dir=in action=allow protocol=TCP localport=35999 profile=private"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=视饭AI主机共享-键鼠通道 dir=in action=allow protocol=TCP localport=24861 profile=private"; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-配对服务"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=视饭AI主机共享-键鼠通道"; Flags: runhidden
