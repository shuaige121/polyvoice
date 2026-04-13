"""Scan Claude Code project transcripts into sanitized vocabulary sources."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from polyvoice.vocab.secrets import redact


SYSTEM_TAG_NAMES = (
    "task-notification",
    "local-command-caveat",
    "command-name",
    "command-message",
    "command-args",
    "local-command-stdout",
    "local-command-stderr",
    "command-stdout",
    "command-stderr",
    "bash-input",
    "bash-stdout",
    "bash-stderr",
    "function_calls",
    "function_result",
    "user-prompt-submit-hook",
    "ide_opened_file",
    "files-attached",
    "policy-spec",
    "system-reminder",
)

SYSTEM_TAG = re.compile(
    rf"<({'|'.join(re.escape(name) for name in SYSTEM_TAG_NAMES)})(?:\s[^>]*)?>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`]+`")
URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
PATH = re.compile(r"(?<!\w)(?:~|\.{1,2})?/[\w./@%+=:,;~#-]+|[A-Za-z]:\\[^\s]+")
JSON_FIELD = re.compile(r'"[A-Za-z_][\w_]*"\s*:')
WHITESPACE = re.compile(r"\s+")
SKIP_MARKERS = (
    "[Request interrupted",
    "<function_calls>",
    "<function_result>",
    "<ide_opened_file>",
    "<files-attached>",
)


def iter_messages(root: Path, *, strict_redact: bool = True) -> Iterable[dict[str, Any]]:
    """Yield cleaned user text messages from Claude Code JSONL transcripts."""

    for path in sorted(root.expanduser().glob("*/*.jsonl")):
        session_id = path.stem
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = payload.get("message", payload)
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                for text in _content_to_texts(message.get("content")):
                    if any(marker in text for marker in SKIP_MARKERS):
                        continue
                    cleaned = clean_text(text, strict_redact=strict_redact)
                    if not cleaned or _looks_like_pasted_data(cleaned):
                        continue
                    yield {
                        "session_id": session_id,
                        "role": "user",
                        "type": "text",
                        "text": cleaned,
                        "ts": payload.get("timestamp") or payload.get("ts"),
                        "source": str(path),
                    }


def scan(root: Path, out: Path, *, strict_redact: bool = True, dry_run: bool = False) -> int:
    rows = list(iter_messages(root, strict_redact=strict_redact))
    if dry_run:
        return len(rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for item in rows:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(rows)


def default_scan_out() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("vocab/sources") / f"scan-{stamp}.jsonl"


def clean_text(text: str, *, strict_redact: bool = True) -> str:
    text = SYSTEM_TAG.sub(" ", text)
    text = CODE_BLOCK.sub(" ", text)
    text = INLINE_CODE.sub(" ", text)
    text = URL.sub(" ", text)
    text = PATH.sub(" ", text)
    if strict_redact:
        text = redact(text)
    return WHITESPACE.sub(" ", text).strip()


def _content_to_texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        out = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                out.append(str(item.get("text", "")))
        return out
    return []


def _looks_like_pasted_data(text: str) -> bool:
    if len(text) > 600:
        return True
    if len(JSON_FIELD.findall(text)) >= 3:
        return True
    return text.count("{") + text.count("}") > 4
