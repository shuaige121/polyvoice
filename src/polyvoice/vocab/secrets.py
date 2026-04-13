"""Small regex denylist for vocabulary secret filtering and redaction."""

from __future__ import annotations

import re


# Local denylist only; intentionally avoids runtime secret-scanning dependencies.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcfat_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b[0-9a-fA-F]{32,64}\b"),
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY)\b"),
    re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}\b"),
)


def is_secret(term: str) -> bool:
    value = term.strip()
    if not value:
        return False
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
