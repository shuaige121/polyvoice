# polyvoice Windows App

The Windows app includes the backend, first-run wizard, settings window, system tray shell, and
v0.1 packaging scripts:

- config, path, and rotating JSON log setup under `%LOCALAPPDATA%\polyvoice`
- `sounddevice` microphone recording as mono int16 16 kHz PCM
- lazy local SenseVoice STT through `sherpa-onnx`, or a WSL HTTP route
- hotword post-processing ported from `src/polyvoice/vocab/postprocess.py`
- pywin32 clipboard paste with `SendInput` Ctrl+V
- Win32 `RegisterHotKey` plus `GetAsyncKeyState` release polling
- `idle -> recording -> transcribing -> pasting -> idle` dictation state machine
- CLI probe and full pipeline mode without a GUI
- PySide6 first-run setup wizard and post-install settings window
- QSystemTrayIcon status/menu surface with hotkey lifecycle handling
- WSL Claude history vocabulary refresh that writes `%LOCALAPPDATA%\polyvoice\hotwords.txt`
- Python 3.12 embeddable packaging plus a per-user NSIS installer

## Install

From this directory:

```powershell
python -m pip install -e .
```

For tests:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

Headless CI can skip GUI validation tests explicitly:

```powershell
$env:PYVOICE_SKIP_GUI_TESTS = "1"
python -m pytest
```

## Tray App

```powershell
python -m polyvoice_app.main
```

On first launch, the wizard runs before the tray appears. The wizard checks for WSL STT at
`http://127.0.0.1:7892/health`, starts the Phase 1 model-download stub if WSL is unavailable,
requires you to choose a non-default hotkey, and offers optional local vocabulary refresh and TTS.

For a Windows Python 3.13 smoke run that opens the wizard without blocking on the final hotkey test:

```powershell
python -m polyvoice_app.main --dry-wizard
```

To re-trigger the wizard, remove the settings file:

```powershell
Remove-Item "$env:LOCALAPPDATA\polyvoice\settings.json"
```

## Probe

```powershell
python -m polyvoice_app.cli --probe
```

The probe prints:

- config and log paths
- detected input microphones
- local model readiness or WSL STT route
- a bounded global hotkey registration test

The local model is expected at:

```text
%LOCALAPPDATA%\polyvoice\models\sense-voice-zh-en-ja-ko-yue-2024-07-17\model.int8.onnx
%LOCALAPPDATA%\polyvoice\models\sense-voice-zh-en-ja-ko-yue-2024-07-17\tokens.txt
```

Download the local int8 SenseVoice model on first run or manually:

```powershell
python scripts\download-model.py
```

The downloader uses resume support, verifies the k2-fsa GitHub release SHA256 digest for the int8
archive (`7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e`), extracts only
`model.int8.onnx` and `tokens.txt`, and keeps the model outside the installer. If k2-fsa ever
replaces that asset without a published digest, download once in a controlled environment, compute
`Get-FileHash -Algorithm SHA256`, and update `scripts\download-model.py` in the same change.

## Packaging

Install NSIS before building the installer:

```powershell
scoop install nsis
# or
choco install nsis
```

Build the embeddable app and installer:

```powershell
pwsh scripts\ci-build.ps1
```

This produces:

```text
windows-app\dist\polyvoice-embed\
windows-app\dist\polyvoice-installer-v0.1.exe
```

`scripts\ci-build.ps1` fails with install instructions before the installer step if `makensis` is unavailable. The
installer is per-user, defaults to `%LOCALAPPDATA%\Programs\polyvoice`, does not require admin,
does not use PyInstaller, and does not bundle the SenseVoice model.

## CLI Dictation

```powershell
python -m polyvoice_app.cli
```

Hold the configured hotkey, speak, and release. The CLI records microphone audio, transcribes it,
applies hotword post-processing, and pastes the result into the focused window.

Default config is written to:

```text
%LOCALAPPDATA%\polyvoice\settings.json
```

No hotkey is configured by default. The wizard requires an explicit key choice and validates it
with `RegisterHotKey` before saving.

## Notes

Linux/WSL unit tests do not require a real microphone, pywin32, or a SenseVoice model. Runtime
Windows-only features are imported lazily and report actionable errors when unavailable.

Known limitations:

- v0.1 is unsigned. Windows Defender default scanning should handle the plain Python files without
  PyInstaller unpacking behavior or a global hook DLL.
- Auto-update is not implemented. The installer writes HKCU registry install metadata for future
  updaters.
