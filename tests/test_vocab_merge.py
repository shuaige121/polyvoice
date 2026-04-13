import json
from pathlib import Path

from polyvoice.vocab.adapters import generate
from polyvoice.vocab.merge import merge


def test_vocab_merge_and_adapters(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "phrases.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"phrase": "CosyVoice3", "lang": "en", "category": "library"}),
                json.dumps({"phrase": "RAG", "lang": "en", "category": "acronym", "aliases": ["rag"]}),
                json.dumps({"phrase": "语音模式", "lang": "zh", "category": "domain"}),
                json.dumps({"phrase": "cosyvoice3", "lang": "en", "category": "library"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert merge(tmp_path) == 3
    rows = [json.loads(line) for line in (tmp_path / "master.jsonl").read_text(encoding="utf-8").splitlines()]
    cosy = next(item for item in rows if item["phrase"] == "CosyVoice3")
    assert cosy["count"] == 2
    files = generate(tmp_path)
    assert files["sensevoice"].exists()
    assert "CosyVoice3" in files["sherpa_onnx"].read_text(encoding="utf-8")
    assert "rag\tRAG" in files["capswriter_hot_rule"].read_text(encoding="utf-8")
