"""TOML configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # pragma: no cover - Python 3.10 fallback
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path("~/.config/polyvoice/config.toml").expanduser()


def _expand_path(value: str | os.PathLike[str]) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


@dataclass(frozen=True)
class TTSConfig:
    backend: str = "edge_tts"
    port: int = 7891
    default_voice: str = "f1"
    backends: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class STTConfig:
    backend: str = "sensevoice"
    port: int = 7892
    hotwords_file: Path = ROOT / "vocab/adapters/sensevoice.txt"
    backends: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceModeConfig:
    flag_file: Path = Path("~/.config/polyvoice/active").expanduser()
    max_tts_chars: int = 400
    summarize_model: str = "claude-haiku-4-5"


@dataclass(frozen=True)
class Config:
    path: Path | None
    tts: TTSConfig
    stt: STTConfig
    voice_mode: VoiceModeConfig


def _backend_paths(backends: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, values in backends.items():
        converted = dict(values)
        for key in ("venv", "model_path", "voices_dir"):
            if key in converted and isinstance(converted[key], str):
                converted[key] = _expand_path(converted[key])
        out[name] = converted
    return out


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    config_path = Path(path).expanduser() if path else DEFAULT_CONFIG
    raw: dict[str, Any] = {}
    actual_path: Path | None = None
    if config_path.exists():
        actual_path = config_path
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))

    tts_raw = raw.get("tts", {})
    stt_raw = raw.get("stt", {})
    vm_raw = raw.get("voice_mode", {})

    tts = TTSConfig(
        backend=str(tts_raw.get("backend", "edge_tts")),
        port=int(tts_raw.get("port", 7891)),
        default_voice=str(tts_raw.get("default_voice", "f1")),
        backends=_backend_paths(dict(tts_raw.get("backends", {}))),
    )
    stt = STTConfig(
        backend=str(stt_raw.get("backend", "sensevoice")),
        port=int(stt_raw.get("port", 7892)),
        hotwords_file=_expand_path(str(stt_raw.get("hotwords_file", "vocab/adapters/sensevoice.txt"))),
        backends=_backend_paths(dict(stt_raw.get("backends", {}))),
    )
    voice_mode = VoiceModeConfig(
        flag_file=Path(str(vm_raw.get("flag_file", "~/.config/polyvoice/active"))).expanduser(),
        max_tts_chars=int(vm_raw.get("max_tts_chars", 400)),
        summarize_model=str(vm_raw.get("summarize_model", "claude-haiku-4-5")),
    )
    return Config(path=actual_path, tts=tts, stt=stt, voice_mode=voice_mode)
