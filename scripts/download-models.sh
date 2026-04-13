#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p models

"$ROOT/venvs/cosyvoice/bin/python" - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    local_dir="models/Fun-CosyVoice3-0.5B-2512",
    local_dir_use_symlinks=False,
)
PY
