"""Well-known filesystem paths for the Windows app."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "polyvoice"
MODEL_NAME = "sense-voice-zh-en-ja-ko-yue-2024-07-17"


def local_app_data() -> Path:
    """Return the Windows local app data directory, with a testable fallback."""
    value = os.environ.get("LOCALAPPDATA")
    if value:
        return Path(value)
    return Path.home() / "AppData" / "Local"


def app_dir() -> Path:
    return local_app_data() / APP_NAME


def config_path() -> Path:
    return app_dir() / "settings.json"


def logs_dir() -> Path:
    return app_dir() / "logs"


def log_path() -> Path:
    return logs_dir() / "polyvoice.log"


def models_dir() -> Path:
    return app_dir() / "models"


def default_model_dir() -> Path:
    return models_dir() / MODEL_NAME


def default_model_path() -> Path:
    return default_model_dir() / "model.int8.onnx"


def default_tokens_path() -> Path:
    return default_model_dir() / "tokens.txt"


def hotwords_path() -> Path:
    return app_dir() / "hotwords.txt"


def master_vocab_path() -> Path:
    return app_dir() / "master.jsonl"


def ensure_app_dirs() -> None:
    app_dir().mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    models_dir().mkdir(parents=True, exist_ok=True)
