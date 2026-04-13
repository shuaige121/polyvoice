import json
from pathlib import Path

from polyvoice.vocab.scan import iter_messages, scan


def test_scan_user_text_only_and_sanitizes(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    transcript = project / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"message": {"role": "assistant", "content": "ignore CosyVoice3"}}),
                json.dumps({"message": {"role": "user", "content": "[Request interrupted by user]"}}),
                json.dumps(
                    {
                        "timestamp": "2026-04-14T00:00:00Z",
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Please test CosyVoice3 <command-stdout>secret</command-stdout> at /tmp/x https://x.test"},
                                {"type": "tool_result", "content": "ignore"},
                            ],
                        },
                    }
                ),
                json.dumps({"message": {"role": "user", "content": '{"a":1,"b":2,"c":3}'}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rows = list(iter_messages(tmp_path))
    assert len(rows) == 1
    assert rows[0]["role"] == "user"
    assert rows[0]["type"] == "text"
    assert "CosyVoice3" in rows[0]["text"]
    assert "secret" not in rows[0]["text"]
    assert "https" not in rows[0]["text"]
    out = tmp_path / "out.jsonl"
    assert scan(tmp_path, out) == 1
    assert out.exists()
