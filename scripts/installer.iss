; Inno Setup Script for PC Control
; Compliant with Inno Setup 6.x

#define MyAppName "PC Control"
#define MyAppVersion "2.4.0"
#define MyAppPublisher "PC Control"
#define MyAppURL "https://github.com/lavi-666/pc-control"
#define MyAppExeName "Launcher.exe"

[Setup]
AppId={{D37F28B0-8C7F-4B8A-9B3B-864D15F493B1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\PC Control
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PC-Control-Setup
SetupIconFile=..\pc_control.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\pc_control.ico
UninstallDisplayName={#MyAppName}
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startupicon"; Description: "Запускать PC Control при входе в Windows"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Uninstall.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PC_Control.apk"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\pc_control.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\open_app.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements-runtime.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\runtime-source.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.example.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.ru.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\launcher.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\start_server.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\stop_server.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\change_password.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uninstall.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\core\*"; DestDir: "{app}\core"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\modules\*"; DestDir: "{app}\modules"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\web\*"; DestDir: "{app}\web"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\pc_control.ico"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{app}\Uninstall.exe"; IconFilename: "{app}\pc_control.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\pc_control.ico"; Tasks: desktopicon
Name: "{userstartup}\PC_Control_Server"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\pc_control.ico"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Uninstall.exe"; Parameters: "--silent"; Flags: waituntilterminated
