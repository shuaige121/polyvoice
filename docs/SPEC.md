# Implementation Spec

Directive spec for implementers (human or LLM). Assume the scaffold in [ARCHITECTURE.md](ARCHITECTURE.md) is fixed; this doc fills it in.

## Conventions

- Python 3.10+, type hints mandatory on public APIs.
- `ruff` clean, no ignored rules.
- Every worker/server logs to stderr with timestamps; stdout reserved for protocol frames where applicable.
- No globals for model state; pass via class or closure.
- Dependencies installed per backend via `uv venv venvs/<name>` + `uv pip install`. Do not pin everything into the root `pyproject.toml`; root deps only include server/client/shared.
- File paths: backend venvs live in repo-relative `venvs/`; models live in `models/` (gitignored).

## Worker protocol (shared by all backends)

Server spawns worker as subprocess. Communication: **JSON lines over stdin/stdout**. stderr is free-form logs.

### Requests (server → worker, one JSON per line)

```json
{"id": "req-1", "op": "health"}
{"id": "req-2", "op": "list_voices"}
{"id": "req-3", "op": "speak", "text": "你好 CosyVoice3", "voice": "f1", "speed": 1.0}
{"id": "req-4", "op": "transcribe", "pcm_b64": "...", "sr": 16000, "hotwords": ["CosyVoice3"]}
{"id": "req-5", "op": "shutdown"}
```

### Responses (worker → server)

For non-streaming ops (`health`, `list_voices`, `transcribe`):
```json
{"id": "req-1", "ok": true, "result": {...}}
{"id": "req-1", "ok": false, "error": "..."}
```

For streaming ops (`speak`):
```json
{"id": "req-3", "chunk": "<base64 PCM16LE>"}
{"id": "req-3", "chunk": "..."}
{"id": "req-3", "done": true, "sample_rate": 24000}
```

Worker must start yielding `chunk` frames **before** synthesis completes (first chunk latency is measured in tests).

### Worker lifecycle

- Worker boots, loads model, prints single line `{"ready": true, "sample_rate": <int>}` to stdout, then enters request loop.
- Server reads this line before accepting any client request.
- On `shutdown`, worker exits 0.
- Server kills worker with SIGTERM after 5s grace on backend switch.

## Phase 1 — TTS

### Files to create

```
src/polyvoice/server/tts.py          # FastAPI app + router + worker manager
src/polyvoice/server/worker_mgr.py    # shared worker lifecycle code
src/polyvoice/server/audio.py         # WAV header builder, PCM↔bytes helpers
src/polyvoice/backends/tts/edge_tts.py       # cloud fallback backend
src/polyvoice/backends/tts/cosyvoice3.py     # primary local backend
src/polyvoice/backends/tts/worker_entry.py   # subprocess entrypoint (dispatches by backend name)
src/polyvoice/clients/say_zh.py       # CLI client
src/polyvoice/config.py               # TOML config loader
src/polyvoice/logging.py              # structured stderr logger
venvs/edge-tts/requirements.txt
venvs/cosyvoice/requirements.txt
scripts/setup-venvs.sh                # creates all backend venvs via uv
scripts/download-models.sh            # fetches CosyVoice3 weights
tests/test_streaming_wav.py
tests/test_config.py
tests/test_worker_protocol.py
```

### TTS HTTP API (OpenAI-compatible)

```
POST /v1/audio/speech
Content-Type: application/json
Body: {
  "model": "cosyvoice3",          # ignored — we use configured backend; kept for OpenAI-client compat
  "input": "要合成的文本",
  "voice": "f1",                   # backend-specific; server rejects unknown
  "response_format": "wav",        # only "wav" supported initially
  "speed": 1.0
}

Response: 200 OK
  Transfer-Encoding: chunked
  Content-Type: audio/wav
  Body: streaming WAV (header with data_size=0xFFFFFFFF, then PCM16LE)

Errors:
  400 — bad input (empty text, unknown voice)
  503 — worker not ready / crashed
```

Also expose:
- `GET /v1/audio/voices` → `{"voices": [...]}`
- `GET /health` → `{"ok": bool, "backend": str, "sample_rate": int, "uptime_s": float}`
- `POST /admin/switch` → `{"backend": "spark-tts"}` → kills worker, reloads with new backend from config. Returns when new worker is ready.

### Streaming WAV header

```python
# src/polyvoice/server/audio.py
def streaming_wav_header(sample_rate: int, channels: int = 1, bits: int = 16) -> bytes:
    # RIFF with data size 0xFFFFFFFF for unknown-length streaming.
    import struct
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    return (
        b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits)
        + b"data" + struct.pack("<I", 0xFFFFFFFF)
    )
```

### Backend: edge-tts

- Deps: `edge-tts>=6.1`
- Voices: expose Microsoft neural names as-is (`zh-CN-XiaoxiaoNeural`, `zh-CN-YunxiNeural`, `en-US-AriaNeural`, ...).
- Also register short aliases: `f1`→`zh-CN-XiaoxiaoNeural`, `m1`→`zh-CN-YunxiNeural`, `en-f1`→`en-US-AriaNeural`.
- edge-tts produces MP3; worker must decode to PCM16LE mono @ 24kHz using ffmpeg subprocess (or `pydub`) and chunk-yield.
- First-chunk latency target: <800ms.

### Backend: cosyvoice3

- Deps (in `venvs/cosyvoice/requirements.txt`, pinned to FunAudioLLM/CosyVoice repo requirements): torch==2.3.1, torchaudio==2.3.1, + the full CosyVoice requirement list (see upstream repo).
- Clone upstream repo to `third_party/CosyVoice/` during setup; worker imports from there via `sys.path.insert`.
- Model: `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` (download via `modelscope` or `huggingface_hub`).
- Voices: scan `<config.voices_dir>/*.wav` + matching `.txt`; each file pair = one zero-shot voice named after the stem. Ship `assets/voices/f1.wav + f1.txt` and `m1.wav + m1.txt` (use upstream `asset/zero_shot_prompt.wav` for f1; record or source m1 separately — if unavailable, ship only f1 and leave a TODO).
- Use `inference_zero_shot(text, prompt_text, prompt_speech_16k, stream=True, speed=speed)` in a generator; each yielded tensor → int16 PCM → base64 → stdout JSON line.
- First-chunk latency target: <500ms (model loaded).

### say-zh CLI

```
say-zh TEXT [--voice NAME] [--speed 1.0] [--backend NAME] [--url URL] [--list]
```

- Default URL `http://127.0.0.1:7891` (configurable via `POLYVOICE_URL` env).
- Posts to `/v1/audio/speech`, pipes chunked response to `ffplay -loglevel quiet -nodisp -autoexit -i -`.
- If TEXT omitted, reads stdin.
- `--list` → print voices (GET `/v1/audio/voices`).
- `--backend` overrides default by sending `POST /admin/switch` before the speech request (warn user on 10s cold start).

### Phase 1 verification commands

```bash
# Setup
bash scripts/setup-venvs.sh              # creates venvs/edge-tts, venvs/cosyvoice
bash scripts/download-models.sh          # pulls CosyVoice3 model
cp config.example.toml ~/.config/polyvoice/config.toml  # user edits paths

# Unit tests
uv run pytest -q                         # must pass

# Smoke: edge-tts
uv run polyvoice-tts &                   # starts server on :7891 with default (edge-tts if cosyvoice unavailable)
curl -sf http://127.0.0.1:7891/health | jq .
say-zh "你好 polyvoice，这是 edge TTS 的 smoke test"

# Smoke: CosyVoice3 streaming
curl -X POST http://127.0.0.1:7891/admin/switch -d '{"backend":"cosyvoice3"}' -H 'Content-Type: application/json'
say-zh "帮我 deploy 这个 Kubernetes 的 pod，检查 API latency"
# Expected: audio starts <500ms after command, English terms pronounced correctly.

# Streaming proof: first chunk within 1s
time curl -N -X POST http://127.0.0.1:7891/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"cosyvoice3","input":"测试流式","voice":"f1"}' \
  -o /dev/null --max-time 1
# Should produce bytes despite the 1s timeout
```

## Phase 2 — STT + Vocabulary

### Files

```
src/polyvoice/server/stt.py
src/polyvoice/backends/stt/sensevoice.py
src/polyvoice/backends/stt/faster_whisper.py
src/polyvoice/backends/stt/worker_entry.py
src/polyvoice/vocab/scan.py               # walks ~/.claude/projects, extracts text
src/polyvoice/vocab/extract.py            # parallel Sonnet agents → phrases
src/polyvoice/vocab/merge.py              # dedupe into master.jsonl
src/polyvoice/vocab/adapters.py           # per-backend generators
src/polyvoice/vocab/cli.py                # `polyvoice-vocab scan|extract|gen` commands
venvs/sensevoice/requirements.txt          # sherpa-onnx, numpy, soundfile
tests/test_vocab_merge.py
tests/test_stt_roundtrip.py
```

### STT HTTP API (OpenAI-compatible)

```
POST /v1/audio/transcriptions
Content-Type: multipart/form-data
Fields:
  file: audio blob (wav/webm/mp3)
  model: "sensevoice"  (ignored; configured backend used)
  language: "zh" | "en" | "auto"  (optional)
  response_format: "json" | "text"
  x-hotwords: comma-separated list (custom extension; also accepted as form field)

Response 200:
  {"text": "...", "language": "zh", "segments": [...]}
```

### Backend: sensevoice

- Deps (venvs/sensevoice): `sherpa-onnx>=1.10`, `numpy`, `soundfile`.
- Model: `ruska1117/SenseVoiceSmall-onnx-fp16` (fetched in setup).
- Hotwords: sherpa-onnx `OfflineRecognizer` supports `hotwords_file` and `hotwords_score`. Reload when file mtime changes.
- Input audio → decode to 16kHz mono PCM (ffmpeg) → inference → return text.

### Vocab pipeline

#### scan.py

```
polyvoice-vocab scan [--since SESSION_ID] [--out sources/claude-scan-<date>.jsonl]
```

- Walks `~/.claude/projects/*/*.jsonl`, reads every line as JSON.
- Extracts `message.content` where `role in ("user", "assistant")`.
- Output: JSONL of `{session_id, role, text, ts}`.
- `--since`: resume from `state.json.last_scan_session_id`.

#### extract.py

```
polyvoice-vocab extract [--input sources/...] [--parallel 5] [--model claude-sonnet-4-6]
```

- Shards input by session (batch 20 sessions per agent).
- For each shard, calls Anthropic API with a directive prompt:
  ```
  You extract domain vocabulary from user/assistant messages for ASR hotword biasing.
  Return ONLY JSON array. For each phrase output {"phrase": str, "lang": "zh"|"en"|"mixed", "category": "library"|"command"|"project"|"person"|"acronym"|"domain"}.
  Include: library/framework names, CLI commands, project codenames, file path fragments, acronyms (MOM, MOH, RAG), Chinese proper nouns, dictionary-rare technical terms.
  Exclude: common words, numbers, URLs, email addresses.
  ```
- Parallel via `asyncio.gather` (N workers).
- Output: `sources/phrases-<date>.jsonl`.

#### merge.py

- Reads all `sources/*.jsonl` + `manual.txt`.
- Dedupes by normalized phrase (lowercase for en, exact for zh).
- Updates `master.jsonl`:
  - New entry: set `first_seen`, `count=1`, `sources=[input_file]`.
  - Existing: increment `count`, extend `sources`, merge `aliases`.
- Computes `weight`: `min(1.0 + log10(count), 3.0)`.

#### adapters.py

Generates:
- `adapters/sensevoice.txt` — one phrase per line (sherpa-onnx format).
- `adapters/sherpa_onnx.txt` — `<phrase> :<weight>` per line.
- `adapters/capswriter_hot_en.txt` — English only (CapsWriter split).
- `adapters/capswriter_hot_zh.txt` — Chinese only.
- `adapters/capswriter_hot_rule.txt` — from `aliases` field (format `<alias>\t<phrase>`).

### Phase 2 verification

```bash
# Vocab end-to-end
polyvoice-vocab scan --out /tmp/scan.jsonl
polyvoice-vocab extract --input /tmp/scan.jsonl --parallel 3
polyvoice-vocab merge
polyvoice-vocab gen
ls vocab/adapters/                         # all four files present
head vocab/master.jsonl

# STT smoke
uv run polyvoice-stt &                     # :7892
arecord -d 3 -f cd -r 16000 -c 1 test.wav  # or any 16kHz wav
curl -F file=@test.wav -F language=auto http://127.0.0.1:7892/v1/audio/transcriptions
# With hotwords
curl -F file=@test.wav -F language=auto -F x-hotwords=CosyVoice3,polyvoice \
  http://127.0.0.1:7892/v1/audio/transcriptions
```

## Phase 3 — Claude Code integration

### Files

```
src/polyvoice/hooks/stop.py          # Stop hook script
src/polyvoice/hooks/session_init.py  # injects voice-mode prompt
src/polyvoice/voice_mode.py          # flag file r/w, toggle
scripts/install-hooks.sh             # symlinks to ~/.claude/hooks + settings patch
docs/VOICE_MODE.md
assets/voice_mode_prompt.md
```

### voice_mode.md (shipped prompt)

Content already drafted in earlier conversation; paste into `assets/voice_mode_prompt.md`:

```
你正处于语音对话模式。用户说话、系统朗读你的回复。

回答规则：
- 简短：默认 ≤150 字，对话感，不写 markdown 结构
- 不念代码：涉及代码时说"已改好 X，主要改动是 Y 和 Z"，别贴源码
- 不用表格/bullet-heavy 列表
- 专有名词用英文原词，别音译
- 版本号/路径分段清楚，不连读
- 需要贴大段内容时说"我放在上方了"

若用户明显在让你写代码而非对话（如"写个函数"），回归标准模式。
```

### Activation

- `polyvoice voice on` → touches `~/.config/polyvoice/active`, prints confirmation.
- `polyvoice voice off` → removes flag.
- `session_init.py` hook: if flag exists, emit the voice_mode_prompt as additional context.

### Stop hook

Read hook payload (stdin JSON) with fields per Claude Code docs (transcript_path, session_id, ...).

Algorithm:
```
1. If flag file missing → exit 0.
2. Parse transcript_path (jsonl); find last assistant message.
3. Check recent tool calls in transcript: if any Bash call matches /\bsay-zh\b/ within this turn → exit 0.
4. text = strip_markdown(last_assistant.content)
5. If len(text) > config.max_tts_chars OR code_ratio(text) > 0.4:
      if code_ratio high → play short chime (assets/chime.wav) via ffplay → exit 0
      else → summarize via Haiku to ≤150 chars
6. POST /v1/audio/speech with text → stream to ffplay
7. exit 0
```

Strip rules: remove fenced code blocks entirely, remove markdown links `[x](y)` → `x`, strip `*#` emphasis, collapse whitespace.

### install-hooks.sh

- Writes `~/.claude/settings.json` additions (merge, do not overwrite) for `hooks.Stop` and `hooks.SessionStart`.
- Creates `~/.config/polyvoice/` with `config.toml` from example (if absent).
- Validates: tts-server is reachable, flag file path writable.

### Phase 3 verification

```bash
bash scripts/install-hooks.sh
polyvoice voice on
# In Claude Code, ask a short question — response should be spoken.
# Ask for code — response should play chime, not speak code.
polyvoice voice off
# Responses no longer spoken.
```

## Out of scope for this spec

- CapsWriter-Offline integration (Windows side; separate doc).
- Wake-word / always-on mic.
- MCP server wrapper (voicemode covers that path; defer).

## Testing matrix

| Layer | Kind | Tool |
|---|---|---|
| Config / utils | unit | pytest |
| Worker protocol | unit (mock worker) | pytest |
| WAV header streaming | unit | pytest (byte inspection) |
| edge-tts backend | integration, requires network | pytest -m net |
| cosyvoice3 backend | integration, requires GPU | pytest -m gpu |
| sensevoice backend | integration, requires GPU or CPU | pytest -m gpu_or_cpu |
| Vocab pipeline | integration with fixture jsonl | pytest |
| Stop hook | integration against running server | pytest -m e2e |

Default `pytest` run skips `net/gpu/e2e`; CI runs unit tier only.

## Definition of done (per phase)

- **P1 done**: `say-zh "中英混杂 test 一下"` plays within 500ms on cosyvoice3; switching to edge-tts works; all P1 unit tests pass.
- **P2 done**: `polyvoice-vocab` generates `master.jsonl` from real `~/.claude/projects`; SenseVoice transcribes test.wav correctly; hotwords detectably change output.
- **P3 done**: flag toggle controls whether Claude Code replies are spoken; code-heavy replies trigger chime instead; no double-play when Claude calls say-zh explicitly.
