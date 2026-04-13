from pathlib import Path

import pytest

from polyvoice.vocab.ime_import import import_ime


def test_ime_import_plain_text_and_rejects_scel(tmp_path: Path) -> None:
    src = tmp_path / "userdb.txt"
    src.write_text("语音模式\tabc\t1\nCosyVoice3 code 3\n", encoding="utf-8")
    out = tmp_path / "candidates.jsonl"
    assert import_ime([src], out) == 2
    text = out.read_text(encoding="utf-8")
    assert '"sources": ["ime"]' in text
    with pytest.raises(ValueError):
        import_ime([tmp_path / "x.scel"], out)
