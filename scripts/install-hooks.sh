#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${HOME}/.claude"
HOOK_DIR="${CLAUDE_DIR}/hooks"
CONFIG_DIR="${HOME}/.config/polyvoice"
SETTINGS="${CLAUDE_DIR}/settings.json"

mkdir -p "$HOOK_DIR" "$CONFIG_DIR"
ln -sfn "$ROOT/src/polyvoice/hooks/stop.py" "$HOOK_DIR/polyvoice-stop.py"
ln -sfn "$ROOT/src/polyvoice/hooks/session_init.py" "$HOOK_DIR/polyvoice-session-init.py"

if [ ! -f "$CONFIG_DIR/config.toml" ]; then
  cp "$ROOT/config.example.toml" "$CONFIG_DIR/config.toml"
fi

python3 - "$SETTINGS" "$HOOK_DIR/polyvoice-stop.py" "$HOOK_DIR/polyvoice-session-init.py" <<'PY'
import json
import sys
from pathlib import Path

settings = Path(sys.argv[1])
stop = sys.argv[2]
session = sys.argv[3]
if settings.exists():
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
else:
    data = {}
hooks = data.setdefault("hooks", {})
hooks["Stop"] = [{"hooks": [{"type": "command", "command": f"python3 {stop}"}]}]
hooks["SessionStart"] = [{"hooks": [{"type": "command", "command": f"python3 {session}"}]}]
settings.parent.mkdir(parents=True, exist_ok=True)
settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

test -w "$CONFIG_DIR"
if curl --max-time 2 -sf http://127.0.0.1:7891/health >/dev/null; then
  echo "polyvoice TTS server reachable"
else
  echo "warning: polyvoice TTS server is not reachable at http://127.0.0.1:7891" >&2
fi
echo "installed Claude Code hooks in $HOOK_DIR"
