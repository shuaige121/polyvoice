from __future__ import annotations

import json

from polyvoice_app import config


def test_load_config_creates_schema_v1(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    loaded = config.load_config()

    assert loaded.path == tmp_path / "polyvoice" / "settings.json"
    assert loaded.data["schema_version"] == 1
    assert loaded.data["hotkey"]["vk"] == 0x70


def test_load_config_migrates_with_backup(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 0, "log_level": "DEBUG"}), encoding="utf-8")

    loaded = config.load_config(path)

    assert loaded.data["schema_version"] == 1
    assert loaded.data["log_level"] == "DEBUG"
    assert path.with_suffix(".json.bak").exists()
