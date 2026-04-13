#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

uv venv --allow-existing venvs/edge-tts
uv pip install --python venvs/edge-tts/bin/python -r venvs/edge-tts/requirements.txt -e .

uv venv --allow-existing venvs/cosyvoice
uv pip install --python venvs/cosyvoice/bin/python "setuptools<81" wheel hatchling editables numpy==1.26.4
uv pip install --no-build-isolation --index-strategy unsafe-best-match --python venvs/cosyvoice/bin/python -r venvs/cosyvoice/requirements.txt -e .

uv venv --allow-existing venvs/sensevoice
uv pip install --python venvs/sensevoice/bin/python -r venvs/sensevoice/requirements.txt -e .

if [ ! -d third_party/CosyVoice ]; then
  mkdir -p third_party
  git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git third_party/CosyVoice
fi
git -C third_party/CosyVoice submodule update --init --recursive
