from __future__ import annotations

import json
import subprocess
from pathlib import Path

from polyvoice_app import paths, vocab


def test_enumerate_wsl_distros_decodes_utf16(monkeypatch):
    output = "Ubuntu\nDebian\n".encode("utf-16-le")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout=output, stderr=b"")

    monkeypatch.setattr(vocab.subprocess, "run", fake_run)

    assert vocab.enumerate_wsl_distros() == ["Ubuntu", "Debian"]


def test_refresh_from_wsl_writes_hotwords_and_master(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    project_root = tmp_path / "projects"
    session_dir = project_root / "demo"
    session_dir.mkdir(parents=True)
    transcript = session_dir / "session.jsonl"
    rows = [
        {"message": {"role": "user", "content": "请使用 PolyVoiceEngine 处理 领域热词"}},
        {"message": {"role": "user", "content": [{"type": "text", "text": "PolyVoiceEngine 领域热词 再测试"}]}},
        {"message": {"role": "assistant", "content": "不应该扫描助手回复 PolyVoiceEngine"}},
    ]
    transcript.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    root = vocab.WslProjectRoot("Ubuntu", "alice", project_root, r"\\wsl.localhost")
    monkeypatch.setattr(vocab, "enumerate_wsl_distros", lambda: ["Ubuntu"])
    monkeypatch.setattr(vocab, "find_claude_project_roots", lambda distro: [root])
    monkeypatch.setattr(vocab, "term_zipf", lambda term: 1.0)

    result = vocab.refresh_from_wsl()

    assert result.messages == 2
    assert "PolyVoiceEngine" in paths.hotwords_path().read_text(encoding="utf-8")
    master = [json.loads(line) for line in paths.master_vocab_path().read_text(encoding="utf-8").splitlines()]
    assert any(item["phrase"] == "PolyVoiceEngine" for item in master)
    assert all("助手回复" not in json.dumps(item, ensure_ascii=False) for item in master)


def test_find_claude_project_roots_tries_user_root_and_home_dirs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "bob" / ".claude" / "projects").mkdir(parents=True)
    seen: list[Path] = []

    def fake_start(_distro):
        return None

    def fake_path(value: str):
        assert "Ubuntu" in value
        return home

    def fake_is_dir(path: Path) -> bool:
        seen.append(path)
        return path.is_dir()

    monkeypatch.setenv("USERNAME", "alice")
    monkeypatch.setattr(vocab, "start_wsl_distro", fake_start)
    monkeypatch.setattr(vocab, "Path", fake_path)
    monkeypatch.setattr(vocab, "_is_dir", fake_is_dir)

    roots = vocab.find_claude_project_roots("Ubuntu")

    assert [root.user for root in roots] == ["bob", "bob"]
    assert any("alice" in str(path) for path in seen)
    assert any("root" in str(path) for path in seen)
