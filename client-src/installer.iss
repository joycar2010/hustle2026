; Quant Hedge 交易终端 安装脚本 (Inno Setup 6)
; 安装器可在 Win7-Win11 运行; 程序本体需 Win10 1607+/Win11(.NET8+WebView2)
#define AppName "Quant Hedge 交易终端"
#define AppVer "1.1.0"
#define AppExe "QuantHedge.exe"
#define AppPublisher "Quant Hedge"

[Setup]
AppId={{8F3A21K9-QH20-26AB-CDEF-QUANTHEDGE001}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\QuantHedge
DefaultGroupName=Quant Hedge
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVer}
OutputDir=C:\Users\Administrator\Desktop
OutputBaseFilename=QuantHedge-Setup-{#AppVer}
SetupIconFile=C:\Users\Administrator\qh_client\app.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
; Inno 自身可跑到 Win7 SP1; 不设 MinVersion 卡死, 改为安装时提示
MinVersion=6.1sp1

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce

[Files]
Source: "C:\Users\Administrator\qh_client\publish_fld\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var V: TWindowsVersion;
begin
  Result := True;
  GetWindowsVersionEx(V);
  // Win10 = 10.0(build>=14393 即 1607); 低于则提示但允许继续(用户自担)
  if (V.Major < 10) then
  begin
    if MsgBox('检测到当前系统低于 Windows 10。' + #13#10 +
              '本程序基于 .NET 8 + WebView2,需 Windows 10 (1607) 或更高版本才能正常运行,' + #13#10 +
              'Windows 7/8 上可安装但可能无法启动。' + #13#10#13#10 +
              '是否仍要继续安装?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end
  else if (V.Major = 10) and (V.Build < 14393) then
  begin
    MsgBox('建议将 Windows 10 更新到 1607 或更高版本以确保正常运行。', mbInformation, MB_OK);
  end;
end;
