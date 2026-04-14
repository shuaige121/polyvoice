"""Load and save settings.json for the Windows app."""

from __future__ import annotations

import json
import logging
import shutil
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from polyvoice_app import paths

logger = logging.getLogger("polyvoice.config")

SCHEMA_VERSION = 1

DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "hotkey": {"vk": 0x70, "modifiers": ["alt"], "toggle": False},
    "mic": {"name": None, "index": None},
    "stt": {
        "route": "local",
        "wsl_url": "http://127.0.0.1:7892",
        "model_dir": None,
    },
    "tts": {
        "enabled": False,
        "url": "http://127.0.0.1:7891",
        "voice": "f1",
    },
    "hook_installed": False,
    "vocab": {"auto_refresh_hours": 24},
    "max_recording_s": 60,
    "log_level": "INFO",
}


@dataclass(frozen=True)
class Config:
    """Small wrapper around raw settings for typed convenience."""

    data: dict[str, Any]
    path: Path

    @property
    def hotkey_vk(self) -> int:
        return int(self.data["hotkey"]["vk"])

    @property
    def hotkey_modifiers(self) -> list[str]:
        return list(self.data["hotkey"].get("modifiers", []))

    @property
    def hotkey_toggle(self) -> bool:
        return bool(self.data["hotkey"].get("toggle", False))

    @property
    def max_recording_s(self) -> float:
        return float(self.data.get("max_recording_s", 60))


def default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)


def _merge_defaults(settings: dict[str, Any]) -> dict[str, Any]:
    merged = default_settings()
    for key, value in settings.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    merged["schema_version"] = SCHEMA_VERSION
    return merged


def _backup(path: Path) -> Path:
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    return backup


def migrate(settings: dict[str, Any], path: Path) -> tuple[dict[str, Any], bool]:
    """Upgrade settings to the current schema.

    Phase 1 only has schema version 1, so unknown or older files are normalized
    by overlaying their values onto defaults and setting schema_version to 1.
    """
    version = settings.get("schema_version")
    if version == SCHEMA_VERSION:
        merged = _merge_defaults(settings)
        return merged, merged != settings
    if path.exists():
        backup = _backup(path)
        logger.info(
            "config backup created",
            extra={"event": "config_backup", "path": str(path), "backup": str(backup)},
        )
    migrated = _merge_defaults(settings)
    logger.info(
        "config migrated",
        extra={"event": "config_migrated", "from_schema": version, "to_schema": SCHEMA_VERSION},
    )
    return migrated, True


def load_config(path: Path | None = None) -> Config:
    config_file = path or paths.config_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    if not config_file.exists():
        settings = default_settings()
        save_config(settings, config_file)
        logger.info("config created", extra={"event": "config_created", "path": str(config_file)})
        return Config(settings, config_file)

    try:
        settings = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = config_file.with_suffix(config_file.suffix + ".invalid")
        shutil.copy2(config_file, backup)
        logger.exception(
            "invalid config json",
            extra={"event": "config_invalid", "path": str(config_file), "backup": str(backup)},
        )
        settings = default_settings()
        save_config(settings, config_file)
        return Config(settings, config_file)

    migrated, changed = migrate(settings, config_file)
    if changed:
        save_config(migrated, config_file)
    return Config(migrated, config_file)


def save_config(settings: dict[str, Any] | Config, path: Path | None = None) -> None:
    if isinstance(settings, Config):
        config_file = path or settings.path
        data = settings.data
    else:
        config_file = path or paths.config_path()
        data = settings
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps(_merge_defaults(data), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("config saved", extra={"event": "config_saved", "path": str(config_file)})
