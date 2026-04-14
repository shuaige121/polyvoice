# Clean Windows Install Smoke Test

Use a clean Windows user account or VM with no existing `%LOCALAPPDATA%\polyvoice` state.

## Build

1. Install prerequisites:
   - PowerShell 7: `winget install Microsoft.PowerShell`
   - NSIS: `scoop install nsis` or `choco install nsis`
2. From `windows-app`, run:
   ```powershell
   pwsh scripts/ci-build.ps1
   ```
3. Confirm the build produces:
   ```text
   windows-app\dist\polyvoice-installer-v0.1.exe
   ```

## Install

1. Copy `dist\polyvoice-installer-v0.1.exe` to the clean user account or VM.
2. Run the installer and accept the default install directory:
   ```text
   %LOCALAPPDATA%\Programs\polyvoice
   ```
3. Confirm the installer does not request elevation.
4. Confirm the installer does not include the SenseVoice model. The first app launch downloads it.

## First Launch

1. Launch polyvoice from the Start Menu shortcut.
2. The first-run wizard should run.
3. Wizard steps should match `docs/WINDOWS_APP_SPEC.md` Phase 2:
   - Welcome: "Set up voice for Claude Code"
   - Engine detection with WSL STT probe or local SenseVoice download
   - Mic and hotkey setup while the model download can continue
   - Optional recognition enhancement from local Claude Code history
   - Optional auto-speak replies via polyvoice TTS
   - Finish page with a real hotkey dictation test
4. Complete the wizard.
5. Confirm the tray icon is visible.

## Runtime Smoke

1. Focus a normal user-level text input.
2. Hold the configured hotkey.
3. Say:
   ```text
   你好 polyvoice 测试一下
   ```
4. Release the hotkey.
5. Confirm recognized text is pasted into the focused input.
6. If TTS is enabled, run a test phrase and confirm it plays back.
7. Confirm the log file has entries for each stage:
   ```text
   %LOCALAPPDATA%\polyvoice\logs\polyvoice.log
   ```

## Uninstall

1. Uninstall polyvoice from Programs and Features.
2. Confirm the program directory is removed:
   ```text
   %LOCALAPPDATA%\Programs\polyvoice
   ```
3. Confirm user data is preserved:
   ```text
   %LOCALAPPDATA%\polyvoice
   ```
4. Confirm the uninstaller displays:
   ```text
   user data preserved at <path>
   ```
