# polyvoice Windows App

Phase 2 implements the backend, first-run wizard, settings window, and system tray shell for
the Windows app:

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
- Phase 2 `vocab.py` placeholder refresh that writes `%LOCALAPPDATA%\polyvoice\hotwords.txt`

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

`scripts/download-model.py` is currently a Phase 1 stub and prints `not implemented yet`.

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
