# polyvoice

Pluggable Chinese-English voice framework for Claude Code. Streaming TTS + STT with OpenAI-compatible API, swappable local backends, user vocabulary extracted from chat history.

## Why

Existing Claude Code voice wrappers ([voicemode](https://github.com/mbailey/voicemode) etc.) ship English-first models (Whisper + Kokoro) that handle Mandarin-English code-switching poorly. `polyvoice` fixes that without reinventing the orchestration layer:

- **TTS**: CosyVoice3 / Spark-TTS / Fish-Speech — streaming, 150ms first-packet latency, native zh-en code-switching
- **STT**: SenseVoice-Small (ONNX fp16) — 2.09% CER on AISHELL-1, ~15× faster than Whisper-Large, zh/en/ja/ko/yue in one model
- **API surface**: OpenAI-compatible `/v1/audio/speech` + `/v1/audio/transcriptions` — drop-in for voicemode or any OpenAI-API client
- **Vocabulary**: scans `~/.claude/projects/**/*.jsonl`, extracts domain terms via parallel Sonnet agents, feeds hotwords to STT

## Architecture

```
┌─────────────── Claude Code (MCP / Stop hook) ───────────────┐
│                                                              │
│  voicemode  ──OpenAI HTTP──▶  polyvoice servers              │
│                                    │                         │
│                                    ├─ tts  ─┬─ cosyvoice3    │
│                                    │        ├─ spark-tts     │
│                                    │        └─ edge-tts      │
│                                    │                         │
│                                    └─ stt  ─┬─ sensevoice    │
│                                             └─ faster-whisper│
│                                                              │
│  say-zh  ────────────HTTP─────────▶  (direct CLI)            │
└──────────────────────────────────────────────────────────────┘
        │
        └── vocab/  (master.jsonl → per-backend adapters)
```

Each backend runs in its own venv to avoid torch/onnxruntime conflicts. A thin router in the main server proxies to the active worker.

## Streaming

First-class requirement. Every TTS backend must yield PCM chunks as they're generated; the server exposes them via chunked HTTP transfer so clients play before synthesis completes. No "wait then play".

## Status

🚧 Early scaffolding. Not usable yet.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for detailed design.

## License

MIT
