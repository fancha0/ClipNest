; ClipNest 安装包脚本（Inno Setup）
; 免管理员安装：装到 %LOCALAPPDATA%\Programs\ClipNest，与应用内自动更新兼容
; 用法：ISCC.exe installer\clipnest.iss /DMyAppVersion=0.1.7

#ifndef MyAppVersion
  #define MyAppVersion "0.1.6"
#endif

#define MyAppName "ClipNest"
#define MyAppPublisher "fancha0"
#define MyAppExeName "ClipNest.exe"

[Setup]
AppId={{7C4E9A2D-1B3F-4E5A-9C8D-2F6A0E1B3D45}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright=Copyright (C) 2026 {#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=ClipNest Setup

; 免管理员安装（仅当前用户）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

DefaultDirName={localappdata}\Programs\ClipNest
DisableDirPage=yes
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
AppendDefaultDirName=no

WizardStyle=modern
WizardSizePercent=110,125
SetupIconFile=..\assets\clipnest.ico

OutputDir=..\dist
OutputBaseFilename=ClipNest-Setup
Compression=lzma2/ultra64
SolidCompression=yes

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

CloseApplications=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ClipNest\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; AppUserModelID: "{#MyAppPublisher}.{#MyAppName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; AppUserModelID: "{#MyAppPublisher}.{#MyAppName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
