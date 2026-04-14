# polyvoice Windows App

Phase 1 implements the backend and headless CLI smoke path for the Windows app:

- config, path, and rotating JSON log setup under `%LOCALAPPDATA%\polyvoice`
- `sounddevice` microphone recording as mono int16 16 kHz PCM
- lazy local SenseVoice STT through `sherpa-onnx`, or a WSL HTTP route
- hotword post-processing ported from `src/polyvoice/vocab/postprocess.py`
- pywin32 clipboard paste with `SendInput` Ctrl+V
- Win32 `RegisterHotKey` plus `GetAsyncKeyState` release polling
- `idle -> recording -> transcribing -> pasting -> idle` dictation state machine
- CLI probe and full pipeline mode without a GUI

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

Default hotkey is `ALT+F1` (`vk: 0x70`).

## Notes

Linux/WSL unit tests do not require a real microphone, pywin32, or a SenseVoice model. Runtime
Windows-only features are imported lazily and report actionable errors when unavailable.
