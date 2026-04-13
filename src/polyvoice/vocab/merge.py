"""Merge extracted and manual vocabulary into master.jsonl."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


def merge(vocab_dir: Path = Path("vocab")) -> int:
    master = vocab_dir / "master.jsonl"
    entries = _read_master(master)
    now = datetime.now().isoformat(timespec="seconds")
    for source in sorted((vocab_dir / "sources").glob("*.jsonl")):
        for item in _read_jsonl(source):
            phrase = str(item.get("phrase", "")).strip()
            if not phrase:
                continue
            key = _norm(phrase, str(item.get("lang", "mixed")))
            existing = entries.get(key)
            if existing is None:
                existing = {
                    "phrase": phrase,
                    "lang": item.get("lang", "mixed"),
                    "category": item.get("category", "domain"),
                    "aliases": item.get("aliases", []),
                    "first_seen": now,
                    "count": 0,
                    "sources": [],
                }
                entries[key] = existing
            existing["count"] = int(existing.get("count", 0)) + 1
            existing["sources"] = sorted({*existing.get("sources", []), str(source)})
            existing["weight"] = min(1.0 + math.log10(int(existing["count"])), 3.0)
    manual = vocab_dir / "manual.txt"
    if manual.exists():
        for line in manual.read_text(encoding="utf-8").splitlines():
            phrase = line.strip()
            if phrase:
                key = _norm(phrase, "mixed")
                entries.setdefault(
                    key,
                    {
                        "phrase": phrase,
                        "lang": "mixed",
                        "category": "domain",
                        "aliases": [],
                        "first_seen": now,
                        "count": 1,
                        "sources": [str(manual)],
                        "weight": 1.0,
                    },
                )
    master.parent.mkdir(parents=True, exist_ok=True)
    with master.open("w", encoding="utf-8") as handle:
        for item in sorted(entries.values(), key=lambda value: value["phrase"].lower()):
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(entries)


def _read_master(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out = {}
    for item in _read_jsonl(path):
        out[_norm(str(item["phrase"]), str(item.get("lang", "mixed")))] = item
    return out


def _read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _norm(phrase: str, lang: str) -> str:
    return phrase if lang == "zh" else phrase.lower()
