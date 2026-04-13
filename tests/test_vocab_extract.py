from polyvoice.vocab.extract import build_candidates, render_review


def test_extract_scores_rare_terms_and_snippets() -> None:
    records = [
        {"session_id": "s1", "text": "CosyVoice3 handles 语音模式 and Kubernetes hotwords"},
        {"session_id": "s2", "text": "Please tune CosyVoice3 for 语音模式 with Kubernetes"},
        {"session_id": "s3", "text": "CosyVoice3 语音模式 should redact sk-abcdefghijklmnopqrstuvwxyz123456"},
    ]
    rows = build_candidates(records, limit=20)
    terms = {row["term"]: row for row in rows}
    assert "CosyVoice3" in terms
    assert terms["CosyVoice3"]["camel"] is True
    assert "语音" in "".join(terms)
    assert all("sk-" not in snippet["text"] for row in rows for snippet in row["snippets"])
    review = render_review(rows)
    assert "| term | score | count | zipf | snippets |" in review
    assert "CosyVoice3" in review
