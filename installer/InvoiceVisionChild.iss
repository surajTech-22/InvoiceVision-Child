#ifndef AppVersion
  #define AppVersion "2.5.2"
#endif
#ifndef UpdateMode
  #define UpdateMode 0
#endif

#if UpdateMode
  #define OutputName "InvoiceVisionChild_Update"
#else
  #define OutputName "InvoiceVisionChild_Setup"
#endif

[Setup]
AppId=InvoiceVisionChild-Standalone-2026
AppName=Invoice OCR Child
AppVersion={#AppVersion}
AppVerName=Invoice OCR Child {#AppVersion}
AppPublisher=InvoiceVision Child
DefaultDirName={localappdata}\Programs\InvoiceVisionChild
DefaultGroupName=Invoice OCR Child
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
UsePreviousAppDir=yes
OutputDir=..\release
OutputBaseFilename={#OutputName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\InvoiceVisionChild.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
#if UpdateMode
AllowNoIcons=yes
#endif

[Files]
Source: "..\build\publish\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Invoice OCR Child"; Filename: "{app}\InvoiceVisionChild.exe"

[Code]
function InitializeSetup(): Boolean;
var
  ExistingPath: string;
begin
  Result := True;
#if UpdateMode
  // Update.exe must NOT create an entirely new app by accident.
  // Requires a previous standalone Inno installation for this AppId.
  if not RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\InvoiceVisionChild-Standalone-2026_is1',
      'Inno Setup: App Path', ExistingPath) then
  begin
    MsgBox('Invoice OCR Child standalone installation was not found. Use InvoiceVisionChild_Setup.exe for the initial installation. Your existing AAH Child has not been modified.',
      mbError, MB_OK);
    Result := False;
  end
  else if not FileExists(AddBackslash(ExistingPath) + 'InvoiceVisionChild.exe') then
  begin
    MsgBox('Existing Invoice OCR Child executable not found; update cancelled to protect user data.', mbError, MB_OK);
    Result := False;
  end;
#endif
end;
