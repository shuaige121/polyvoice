"""Scan Claude Code project transcripts into source JSONL."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any


def iter_messages(root: Path) -> Iterable[dict[str, Any]]:
    for path in sorted(root.expanduser().glob("*/*.jsonl")):
        session_id = path.stem
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = payload.get("message", payload)
                role = message.get("role")
                if role not in {"user", "assistant"}:
                    continue
                text = _content_to_text(message.get("content"))
                if text:
                    yield {
                        "session_id": session_id,
                        "role": role,
                        "text": text,
                        "ts": payload.get("timestamp") or payload.get("ts"),
                    }


def scan(root: Path, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out.open("w", encoding="utf-8") as handle:
        for item in iter_messages(root):
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            count += 1
    return count


def default_scan_out() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("vocab/sources") / f"claude-scan-{stamp}.jsonl"


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part).strip()
    return ""
