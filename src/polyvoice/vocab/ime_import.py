"""Import plain-text IME dictionaries into vocab candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from polyvoice.vocab.extract import detect_lang
from polyvoice.vocab.secrets import is_secret, redact


def import_ime(inputs: list[Path], candidates_path: Path = Path("vocab/candidates.jsonl"), *, dry_run: bool = False) -> int:
    rows = list(_iter_rows(inputs))
    if dry_run:
        return len(rows)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    with candidates_path.open("a", encoding="utf-8") as handle:
        for item in rows:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(rows)


def _iter_rows(inputs: list[Path]) -> Iterable[dict[str, object]]:
    seen: set[str] = set()
    for path in inputs:
        if path.suffix.lower() == ".scel":
            raise ValueError(".scel binary dictionaries are not supported; export to --txt first")
        for phrase in _read_phrases(path):
            key = phrase.lower()
            if key in seen or is_secret(phrase):
                continue
            seen.add(key)
            yield {
                "schema_version": 1,
                "term": phrase,
                "phrase": phrase,
                "lang": detect_lang(phrase),
                "score": 100.0,
                "count": 10,
                "zipf": 0.0,
                "camel": False,
                "sources": ["ime"],
                "snippets": [{"session_id": "ime", "text": redact(phrase)[:80]}],
            }


def _read_phrases(path: Path) -> Iterable[str]:
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            phrase = _parse_line(line)
            if phrase:
                yield phrase


def _parse_line(line: str) -> str:
    # Rime userdb export lines often contain phrase, code, commit count, and metadata.
    if "\t" in line:
        fields = [field.strip() for field in line.split("\t") if field.strip()]
        if fields:
            return fields[0]
    if " " in line:
        first = line.split(maxsplit=1)[0].strip()
        if first:
            return first
    return line
