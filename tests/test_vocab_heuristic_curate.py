from polyvoice.vocab.heuristic_curate import curate_rows


def test_heuristic_curate_drops_secrets_and_categories() -> None:
    rows = curate_rows(
        [
            {"term": "CosyVoice3", "lang": "en", "count": 2, "score": 20, "sources": ["s1"]},
            {"term": "RAG", "lang": "en", "count": 2, "score": 20},
            {"term": "语音模式", "lang": "zh", "count": 2, "score": 20},
            {"term": "667cba67", "lang": "en", "count": 9, "score": 99},
            {"term": "0x80040315", "lang": "en", "count": 9, "score": 99},
            {"term": "sk-abcdefghijklmnopqrstuvwxyz123456", "lang": "en", "count": 9, "score": 99},
        ]
    )
    by_phrase = {row["phrase"]: row for row in rows}
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in by_phrase
    assert "667cba67" not in by_phrase
    assert "0x80040315" not in by_phrase
    assert by_phrase["CosyVoice3"]["category"] == "library"
    assert by_phrase["CosyVoice3"]["aliases"] == ["cosyvoice3"]
    assert by_phrase["RAG"]["category"] == "acronym"
    assert by_phrase["语音模式"]["category"] == "domain"
