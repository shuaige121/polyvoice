# polyvoice-windows-app SPEC

Directive spec. Implement exactly as stated. When ambiguous, leave `TODO(spec):`.

## Goal

Windows 11 tray app. Push-to-talk hotkey → record → SenseVoice STT (local CPU) → polyvoice hotword post-processing → paste into focused window. Optional TTS via polyvoice server on WSL. Target user: Singapore zh+en professional who wants to voice-chat with Claude Code CLI in Chinese (Claude Code's native `/voice` does not support Chinese).

## Non-goals

Cross-platform. GPU acceleration (DirectML/CUDA). Speaker diarization. Wake-word. LLM post-polish.

## Repo location

New directory `windows-app/` at repo root. Siblings `src/polyvoice/` stay untouched. Shared logic (`postprocess.py`, `vocab/*`) imported or copied; see module notes.

## Components (polyvoice_app/)

All Python. No compiled launchers. PEP 8, type hints, ruff clean.

```
windows-app/
├── polyvoice_app/
│   ├── __init__.py
│   ├── main.py                  # entry: QApp + tray + lifecycle
│   ├── cli.py                   # entry: headless CLI mode, for smoke tests
│   ├── tray.py                  # pystray (QSystemTrayIcon via PySide6)
│   ├── hotkey.py                # Win32 RegisterHotKey + GetAsyncKeyState polling
│   ├── dictation_controller.py  # state machine idle→recording→transcribing→pasting
│   ├── recorder.py              # sounddevice InputStream, int16 mono 16kHz
│   ├── stt.py                   # sherpa-onnx OfflineRecognizer (SenseVoice int8)
│   ├── postprocess.py           # variant + alias substitution (port from src/polyvoice/vocab/postprocess.py)
│   ├── vocab.py                 # WSL distro probe, ~/.claude/projects scan, jieba+zipf candidates, writes hotwords.txt
│   ├── paste.py                 # pywin32 clipboard save/restore + SendInput Ctrl+V
│   ├── tts_client.py            # optional HTTP POST to polyvoice TTS server
│   ├── settings_gui.py          # PySide6 settings window
│   ├── wizard.py                # PySide6 first-run wizard
│   ├── config.py                # load/save settings.json with schema_version
│   ├── logging_setup.py         # structured logging to %LOCALAPPDATA%\polyvoice\logs\
│   └── paths.py                 # well-known paths (config, logs, models)
├── scripts/
│   ├── build-embeddable.ps1     # assembles bin/ + lib/ from Python embeddable + pip
│   ├── download-model.py        # fetches SenseVoice int8 with resume
│   └── make-installer.nsi       # NSIS installer script
├── tests/
│   ├── test_postprocess.py
│   ├── test_vocab.py
│   ├── test_config.py
│   └── test_hotkey_smoke.py
├── pyproject.toml
└── README.md
```

## Storage / paths

- **Config**: `%LOCALAPPDATA%\polyvoice\settings.json`
- **Logs**: `%LOCALAPPDATA%\polyvoice\logs\polyvoice.log` (rotating, 5 × 2MB)
- **Models**: `%LOCALAPPDATA%\polyvoice\models\sense-voice-zh-en-ja-ko-yue-2024-07-17\{model.int8.onnx, tokens.txt}`
- **Hotwords**: `%LOCALAPPDATA%\polyvoice\hotwords.txt` (plain, one term per line)
- **Master vocab**: `%LOCALAPPDATA%\polyvoice\master.jsonl` (schema_version: 1, same format as `src/polyvoice/vocab/merge.py` output)

## Config schema (settings.json)

```json
{
  "schema_version": 1,
  "hotkey": { "vk": 0x70, "modifiers": ["alt"] },
  "mic": { "name": "Razer Kiyo", "index": 1 },
  "stt": {
    "route": "local",                          // "local" | "wsl"
    "wsl_url": "http://127.0.0.1:7892",
    "model_dir": null                          // null = default
  },
  "tts": {
    "enabled": false,
    "url": "http://127.0.0.1:7891",
    "voice": "f1"
  },
  "hook_installed": false,
  "vocab": { "auto_refresh_hours": 24 },
  "max_recording_s": 60,
  "log_level": "INFO"
}
```

Migrator: `config.py` checks `schema_version` and upgrades in-place with a backup.

## dictation_controller state machine

States: `idle`, `recording`, `transcribing`, `pasting`, `error`.

Transitions:
- `hotkey_press` on idle → recording (starts `recorder`)
- `hotkey_release` on recording → transcribing (calls `stt.transcribe`)
- `transcribe_done(text)` on transcribing → pasting (calls `paste.paste`)
- `paste_done` on pasting → idle
- any error → error (logs, transitions to idle after 2s)
- `timeout(60s)` on recording → transcribing (auto-stop)

Tray reflects state via tooltip + icon color (green idle/ready, yellow recording/transcribing, red error).

## hotkey.py

- Use `win32gui.RegisterHotKey(None, id=1, modifiers, vk)` to bind.
- Use a threading-safe pumping loop: `GetMessage` → dispatch `WM_HOTKEY`.
- On press (WM_HOTKEY), emit `hotkey_press` event.
- On release: poll `GetAsyncKeyState(vk)` at 20 Hz in a worker thread; emit `hotkey_release` when released.
- If `RegisterHotKey` fails (conflict), raise `HotkeyConflictError`.
- Support toggle mode as config option for keys that can't PTT naturally.

## stt.py

- Load sherpa-onnx `OfflineRecognizer.from_sense_voice(model=..., tokens=..., num_threads=4, provider="cpu", use_itn=True)` lazily (first transcribe call).
- Warmup: at app start (background thread), synthesize a 0.5s silence transcribe call to prime.
- API: `transcribe(pcm_bytes, sr=16000) -> str`. Returns text.
- Raises `STTNotReadyError` if model missing; wizard must have completed or route=wsl.
- If `route=wsl`, `transcribe` POSTs to `stt.wsl_url` instead.

## postprocess.py

Port of `src/polyvoice/vocab/postprocess.py` from main repo. Identical behavior.
Read hotwords from `%LOCALAPPDATA%\polyvoice\hotwords.txt` and master aliases from `master.jsonl`. LRU-cache by mtime.

## recorder.py

- `sounddevice.InputStream(samplerate=16000, channels=1, dtype='int16', device=name_or_index)`
- Returns numpy array at stop.
- Handles `max_recording_s`.
- Tries device by stored name first, fallback to stored index, fallback to default.

## paste.py

- Use `win32clipboard.OpenClipboard / GetClipboardData(CF_UNICODETEXT) / SetClipboardData`.
- Save previous CF_UNICODETEXT content; fail gracefully if not text.
- After setting, send `Ctrl+V` via `SendInput` (not `keybd_event` — SendInput is newer and more reliable).
- Sleep 150ms, then restore previous clipboard.
- If paste target window refuses (e.g., no focus, elevated app), just leave text on clipboard and emit `paste_failed` event.

## vocab.py

- `enumerate_wsl_distros()` via `subprocess.run(["wsl.exe", "-l", "-q"])`.
- For each distro, probe paths:
  ```
  \\wsl.localhost\<distro>\home\<user>\.claude\projects
  \\wsl$\<distro>\home\<user>\.claude\projects
  ```
  where `<user>` tried as current Windows user, then `root`, then each home dir listed under `\home`.
- On scan: walk jsonl, filter role=user type=text, strip system tags (same filters as `src/polyvoice/vocab/scan.py`), produce cleaned texts.
- Tokenize with jieba, score with `tf * (8 - zipf_frequency)` (zh or en), skip zipf>=4.5, CamelCase/ALLCAPS 1.5x bonus.
- Apply secrets denylist (port `src/polyvoice/vocab/secrets.py`).
- Write `hotwords.txt` and append-merge into `master.jsonl`.
- Run in background worker; tray shows "vocab refresh…" state.

## tts_client.py

- `speak(text: str)`: POST `tts.url + /v1/audio/speech` with `{"input": text, "voice": tts.voice}`.
- Stream audio response; play via `sounddevice.OutputStream` (no ffplay dep on Windows).
- Cancel on new `speak()` call or explicit stop.
- Used by optional Claude Code Stop hook: hook script on WSL reads assistant message, POSTs to Windows `tts_client` via HTTP (client listens on `127.0.0.1:7893` for the hook, forwarded via WSL mirror).

## settings_gui.py + wizard.py

PySide6 windows.

**Wizard** (first run, detected via missing `settings.json`):

1. Welcome: "Set up voice for Claude Code"
2. Engine detection (auto-advance):
   - Probe WSL polyvoice STT: if healthy, "Found polyvoice in Ubuntu. Use it (saves 240 MB download)? [Yes / Download local]"
   - If no WSL polyvoice: "Downloading SenseVoice engine (240 MB)…" with progress; start immediately; user can skip to Settings and the download continues in background.
3. Mic + Hotkey (runs IN PARALLEL with download):
   - Mic dropdown + VU meter test
   - Hotkey: "Press the key combination you want" → captures vk + modifiers
4. Enhance recognition (opt-in, default Y if WSL .claude/projects found):
   - "Improve recognition from your Claude Code history? Runs locally, nothing leaves this machine."
   - If yes: queue vocab scan for post-wizard background.
5. Auto-speak replies (opt-in, default N):
   - "Let Claude speak responses aloud via polyvoice TTS?" → if yes AND WSL polyvoice TTS healthy, offer "Install Claude Code Stop hook?"
6. Finish: real test. "Press your hotkey and say 你好 polyvoice 测试一下". Shows recognized text. Success → close wizard, tray visible.

**Settings** (post-install):

Tabs: Engine / Mic + Hotkey / Vocab / TTS & Hook / Advanced (ports, log dir, logs viewer)

## Installer (NSIS)

- Target: `polyvoice-installer.exe` ~30 MB.
- Contents: Python 3.12 embeddable + pth file + our `polyvoice_app/` + dependency wheels pre-installed under `lib/`.
- NSIS script:
  - Install to `%LOCALAPPDATA%\Programs\polyvoice`
  - Create Start Menu shortcut → `bin\pythonw.exe -m polyvoice_app.main`
  - Add to HKCU Run for autostart
  - Uninstaller removes program but not `%LOCALAPPDATA%\polyvoice` (user data)
- Code signing: skip v0.1 (no cert). Document for future.

## Logging

- `logging_setup.py`: RotatingFileHandler at `%LOCALAPPDATA%\polyvoice\logs\polyvoice.log`, 2MB × 5.
- Every module calls `logger = logging.getLogger("polyvoice.<module>")`.
- Structured fields: `event`, `state`, `duration_ms`, `error`.
- On crash, log with `logger.exception(...)` before re-raise.
- `sys.excepthook` and `threading.excepthook` log uncaught.
- Tray menu: "Open Log" → opens log file in Notepad.

## Tray

Minimum indicators (tooltip string):
```
polyvoice — STT: local (ready) | Mic: Razer Kiyo | TTS: off | TTFB: —
```

Icon states by color:
- green = ready
- yellow = recording / transcribing / vocab refresh
- red = stt_init_failed / mic_unavailable / model_missing

Right-click menu:
- Recording indicator (tooltip)
- Settings
- Refresh vocab now
- Toggle TTS
- Reconnect WSL
- Open log
- Quit

## Phases + verification

### Phase 1 — core backend, CLI smoke (4 h)

Files: `paths.py`, `config.py`, `logging_setup.py`, `recorder.py`, `stt.py`, `postprocess.py`, `paste.py`, `hotkey.py`, `dictation_controller.py`, `cli.py`, `tests/*`.

Done when:
```
cd windows-app
python -m pip install -e .
python -m polyvoice_app.cli --probe     # prints detected mics + hotkey test
python -m polyvoice_app.cli             # press hotkey, speak, text pasted
```

CLI mode should exercise full pipeline sans GUI.

### Phase 2 — settings + wizard + tray (3 h)

Files: `tray.py`, `settings_gui.py`, `wizard.py`, `main.py`, `vocab.py`.

Done when:
```
python -m polyvoice_app.main
# Wizard runs on first launch, then tray appears.
# Holding hotkey speaks → transcribes → pastes.
```

### Phase 3 — WSL probe + TTS + hook (2 h)

Files: `tts_client.py`, WSL probe in `vocab.py` and wizard.

Done when:
- Wizard detects running polyvoice STT/TTS on WSL.
- With TTS enabled, `python -m polyvoice_app.main --tts-test "测试"` speaks via WSL server.
- Stop hook install writes valid JSON to WSL settings.json.

### Phase 4 — packaging (3 h)

Files: `scripts/build-embeddable.ps1`, `scripts/download-model.py`, `scripts/make-installer.nsi`.

Done when:
```
# In PowerShell:
pwsh scripts/build-embeddable.ps1
makensis scripts/make-installer.nsi
# Produces dist/polyvoice-installer.exe
```

### Phase 5 — integration test (2 h)

Install fresh on a clean Windows VM (or user's secondary account). Walk through wizard. Verify everything works.

## Dependencies (pyproject.toml)

```
sherpa-onnx>=1.10
sounddevice>=0.4
numpy>=1.26
pywin32>=306
PySide6>=6.6
requests>=2.31
jieba>=0.42
wordfreq>=3.1
```

No `pyperclip` (use pywin32). No `pynput` (use win32).

## Boundaries (DO NOT)

- Do NOT use PyInstaller.
- Do NOT bundle the model into the installer.
- Do NOT use `pynput.keyboard.Listener` for hotkey.
- Do NOT write to `~/.claude/settings.json` without explicit user opt-in.
- Do NOT read/cache user Claude history in Windows temp.
- Do NOT commit any `hotwords.txt` or `master.jsonl` with real user data.
- Do NOT add an `ANTHROPIC_API_KEY` path — we don't use cloud anything.

## Open TODOs acknowledged up front

- Claude Code Stop hook delivery path Windows → WSL: hook calls `http://$WSL_HOST_IP:7893` or similar. Work out at Phase 3 design time.
- EV code-signing: defer. Document in README under "known limitations."
- Auto-update: manual for v0.1. `polyvoice-app update-model` CLI command acceptable.
