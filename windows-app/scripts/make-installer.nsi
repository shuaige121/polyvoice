!include "MUI2.nsh"

!define APP_NAME "polyvoice"
!define APP_VERSION "0.1.0"
!define APP_VERSION_SHORT "0.1"
!define COMPANY_NAME "polyvoice"
!define SOURCE_DIR "${__FILEDIR__}\..\dist\polyvoice-embed"
!define LICENSE_FILE "${__FILEDIR__}\..\..\LICENSE"
!define USER_DATA_DIR "$LOCALAPPDATA\polyvoice"

Name "${APP_NAME}"
OutFile "${__FILEDIR__}\..\dist\polyvoice-installer-v${APP_VERSION_SHORT}.exe"
InstallDir "$LOCALAPPDATA\Programs\polyvoice"
RequestExecutionLevel user
Unicode true

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\polyvoice-launch.bat"
!define MUI_FINISHPAGE_RUN_TEXT "Launch polyvoice"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSE_FILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Section "polyvoice" SecMain
    SetShellVarContext current
    SetOutPath "$INSTDIR"

    IfFileExists "${SOURCE_DIR}\polyvoice-launch.bat" 0 missing_source
    File /r "${SOURCE_DIR}\*.*"
    Goto source_ok

missing_source:
    MessageBox MB_ICONSTOP "Missing packaged app at ${SOURCE_DIR}. Run pwsh scripts\ci-build.ps1 first."
    Abort

source_ok:
    CreateDirectory "$SMPROGRAMS"
    CreateShortcut "$SMPROGRAMS\polyvoice.lnk" "$INSTDIR\polyvoice-launch.bat" "" "$INSTDIR\bin\pythonw.exe" 0
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "polyvoice" '"$INSTDIR\polyvoice-launch.bat"'

    WriteRegStr HKCU "Software\polyvoice" "InstallPath" "$INSTDIR"
    WriteRegStr HKCU "Software\polyvoice" "Version" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\polyvoice" "DisplayName" "polyvoice"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\polyvoice" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\polyvoice" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\polyvoice" "Publisher" "${COMPANY_NAME}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\polyvoice" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\polyvoice" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\polyvoice" "NoRepair" 1

    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
    SetShellVarContext current
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "polyvoice"
    Delete "$SMPROGRAMS\polyvoice.lnk"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\polyvoice"
    DeleteRegKey HKCU "Software\polyvoice"

    RMDir /r "$INSTDIR"
    MessageBox MB_OK "polyvoice was uninstalled. User data preserved at $LOCALAPPDATA\polyvoice"
SectionEnd
