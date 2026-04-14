from __future__ import annotations

import json

from polyvoice_app import config, hook_installer


def test_merge_stop_hook_preserves_unknown_keys_and_hooks(tmp_path):
    settings = {
        "theme": "dark",
        "hooks": {
            "Stop": [{"matcher": "other", "hooks": [{"type": "command", "command": "echo keep"}]}],
            "PreToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "echo pre"}]}],
        },
    }

    merged = hook_installer.merge_stop_hook(settings, hook_installer._hook_entry(tmp_path / "hook.py"))

    assert merged["theme"] == "dark"
    assert merged["hooks"]["PreToolUse"] == settings["hooks"]["PreToolUse"]
    assert any("echo keep" in json.dumps(item) for item in merged["hooks"]["Stop"])
    assert any(hook_installer.SCRIPT_NAME in json.dumps(item) for item in merged["hooks"]["Stop"])


def test_remove_stop_hook_removes_only_polyvoice_entry(tmp_path):
    merged = hook_installer.merge_stop_hook(
        {"hooks": {"Stop": [{"matcher": "other", "hooks": [{"command": "echo keep"}]}]}},
        hook_installer._hook_entry(tmp_path / "hook.py"),
    )

    updated = hook_installer.remove_stop_hook(merged)

    assert len(updated["hooks"]["Stop"]) == 1
    assert updated["hooks"]["Stop"][0]["matcher"] == "other"


def test_install_hook_writes_script_and_settings(tmp_path, monkeypatch):
    cfg = config.Config(config.default_settings(), tmp_path / "settings.json")
    cfg.data["tts"]["enabled"] = True
    claude_dir = tmp_path / ".claude"
    target = hook_installer.HookTarget(
        distro="Ubuntu",
        user="alice",
        claude_dir=claude_dir,
        settings_path=claude_dir / "settings.json",
        script_path=claude_dir / hook_installer.SCRIPT_NAME,
    )
    target.settings_path.parent.mkdir()
    target.settings_path.write_text(json.dumps({"unknown": True}), encoding="utf-8")
    monkeypatch.setattr(hook_installer, "default_target", lambda **_kwargs: target)
    monkeypatch.setattr(hook_installer, "health_check", lambda _url: True)
    monkeypatch.setattr(config, "save_config", lambda _cfg: None)

    result = hook_installer.install_hook(cfg)

    assert result.installed
    assert target.script_path.exists()
    settings = json.loads(target.settings_path.read_text(encoding="utf-8"))
    assert settings["unknown"] is True
    assert hook_installer.SCRIPT_NAME in json.dumps(settings)
    assert cfg.data["hook_installed"] is True
