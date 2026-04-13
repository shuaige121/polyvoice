"""Merge curated and manual vocabulary into schema-versioned master.jsonl."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def merge(vocab_dir: Path = Path("vocab"), curated_paths: list[Path] | None = None, *, dry_run: bool = False) -> int:
    master = vocab_dir / "master.jsonl"
    entries = _read_master(master)
    now = datetime.now().isoformat(timespec="seconds")
    paths = curated_paths if curated_paths is not None else sorted((vocab_dir / "sources").glob("curated-*.jsonl"))

    for source in paths:
        for item in _read_jsonl(source):
            _merge_item(entries, item, source=str(source), now=now, manual=False)

    manual = vocab_dir / "manual.jsonl"
    if manual.exists():
        for item in _read_jsonl(manual):
            _merge_item(entries, item, source=str(manual), now=now, manual=True)

    if dry_run:
        return len(entries)
    master.parent.mkdir(parents=True, exist_ok=True)
    with master.open("w", encoding="utf-8") as handle:
        for item in sorted(entries.values(), key=lambda value: _sort_key(value)):
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(entries)


def _merge_item(
    entries: dict[str, dict[str, Any]],
    item: dict[str, Any],
    *,
    source: str,
    now: str,
    manual: bool,
) -> None:
    phrase = str(item.get("phrase") or item.get("term") or "").strip()
    if not phrase:
        return
    lang = str(item.get("lang", "mixed"))
    key = _norm(phrase, lang)
    count = max(1, int(item.get("count", 1) or 1))
    existing = entries.get(key)
    if existing is None:
        existing = {
            "schema_version": SCHEMA_VERSION,
            "phrase": phrase,
            "lang": lang,
            "category": item.get("category", "domain"),
            "aliases": [],
            "first_seen": item.get("first_seen") or now,
            "last_seen": now,
            "count": 0,
            "sources": [],
            "weight": 1.0,
        }
        entries[key] = existing

    if manual:
        existing["phrase"] = phrase
        existing["lang"] = lang
        existing["category"] = item.get("category", existing.get("category", "domain"))
        existing["manual"] = True
    elif not existing.get("manual"):
        existing["category"] = existing.get("category") or item.get("category", "domain")

    existing["schema_version"] = SCHEMA_VERSION
    existing["count"] = int(existing.get("count", 0)) + count
    existing["first_seen"] = existing.get("first_seen") or now
    existing["last_seen"] = now
    existing["sources"] = sorted({*existing.get("sources", []), source, *item.get("sources", [])})
    existing["aliases"] = sorted({*existing.get("aliases", []), *item.get("aliases", [])})
    existing["weight"] = round(min(1.0 + math.log10(int(existing["count"])), 3.0), 3)


def _read_master(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out = {}
    for item in _read_jsonl(path):
        item["schema_version"] = SCHEMA_VERSION
        out[_norm(str(item["phrase"]), str(item.get("lang", "mixed")))] = item
    return out


def _read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _norm(phrase: str, lang: str) -> str:
    return phrase if lang == "zh" else phrase.lower()


def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item.get("lang", "mixed")), str(item.get("phrase", "")).lower()
