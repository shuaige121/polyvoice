from polyvoice.server.stt import _split_hotwords


def test_split_hotwords_form_value() -> None:
    assert _split_hotwords(None, "CosyVoice3, polyvoice,,RAG") == ["CosyVoice3", "polyvoice", "RAG"]
