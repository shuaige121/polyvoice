from __future__ import annotations

import json

from polyvoice_app import config


def test_load_config_creates_schema_v1(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    loaded = config.load_config()

    assert loaded.path == tmp_path / "polyvoice" / "settings.json"
    assert loaded.data["schema_version"] == 1
    assert loaded.data["hotkey"]["vk"] is None
    assert not config.has_hotkey(loaded)


def test_load_config_migrates_with_backup(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 0, "log_level": "DEBUG"}), encoding="utf-8")

    loaded = config.load_config(path)

    assert loaded.data["schema_version"] == 1
    assert loaded.data["log_level"] == "DEBUG"
    assert path.with_suffix(".json.bak").exists()


def test_migration_adds_phase_2_defaults_without_overwriting_hotkey(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"schema_version": 1, "hotkey": {"vk": 0x41, "modifiers": ["ctrl"]}}),
        encoding="utf-8",
    )

    loaded = config.load_config(path)

    assert loaded.data["hotkey"]["vk"] == 0x41
    assert loaded.data["hotkey"]["modifiers"] == ["ctrl"]
    assert loaded.data["hotkey"]["toggle"] is False
    assert loaded.data["vocab"]["auto_refresh_hours"] == 24
    assert config.has_hotkey(loaded)
