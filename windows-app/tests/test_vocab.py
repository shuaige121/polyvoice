from __future__ import annotations

from polyvoice_app import paths, vocab


def test_refresh_from_wsl_writes_placeholder_hotwords(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    vocab.refresh_from_wsl("Ubuntu")

    hotwords = paths.hotwords_path()
    assert hotwords.exists()
    text = hotwords.read_text(encoding="utf-8")
    assert "Phase 2 placeholder hotwords" in text
    assert "distro=Ubuntu" in text
