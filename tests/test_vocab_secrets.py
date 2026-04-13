from polyvoice.vocab.secrets import is_secret, redact


def test_secret_denylist_and_redaction() -> None:
    assert is_secret("sk-abcdefghijklmnopqrstuvwxyz123456")
    assert is_secret("ghp_abcdefghijklmnopqrstuvwxyz123456")
    assert is_secret("0123456789abcdef0123456789abcdef")
    assert is_secret("550e8400-e29b-41d4-a716-446655440000")
    assert is_secret("https://example.com/token")
    assert is_secret("me@example.com")
    assert not is_secret("CosyVoice3")
    assert "[REDACTED]" in redact("token sk-abcdefghijklmnopqrstuvwxyz123456 leaked")
