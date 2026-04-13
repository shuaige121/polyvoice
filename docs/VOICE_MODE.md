# Voice Mode

Voice mode lets Claude Code speak short assistant replies through the local polyvoice TTS server.

## Setup

```bash
bash scripts/install-hooks.sh
polyvoice voice on
```

The installer creates symlinks in `~/.claude/hooks`, ensures `~/.config/polyvoice/config.toml` exists, and merges `Stop` plus `SessionStart` hook entries into `~/.claude/settings.json`.

## Behavior

- `polyvoice voice on` creates `~/.config/polyvoice/active`.
- `polyvoice voice off` removes the flag.
- The SessionStart hook injects `assets/voice_mode_prompt.md` only when the flag exists.
- The Stop hook reads the transcript, strips markdown, skips duplicate playback if the turn already called `say-zh`, and streams speech through `/v1/audio/speech`.
- Code-heavy replies play `assets/chime.wav` instead of spoken code.

Long replies are summarized with the configured Haiku model when `ANTHROPIC_API_KEY` is available; otherwise they are truncated to `max_tts_chars`.
