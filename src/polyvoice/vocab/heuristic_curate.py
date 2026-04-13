"""Deterministic vocabulary curation rules."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from polyvoice.vocab.extract import detect_lang
from polyvoice.vocab.secrets import is_secret


CAMEL = re.compile(r"^[A-Z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*$")
ALL_CAPS = re.compile(r"^[A-Z0-9_]{2,12}$")
ID_LIKE = re.compile(r"^(?=.*\d)(?=.*_)[A-Za-z0-9_]+$")
SHORT_HEX = re.compile(r"^(?:0x)?[0-9a-fA-F]{4,31}$")


def default_curated_out() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("vocab/sources") / f"curated-{stamp}.jsonl"


def curate(input_path: Path, out: Path, *, dry_run: bool = False) -> int:
    rows = list(curate_rows(_read_jsonl(input_path)))
    if dry_run:
        return len(rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for item in rows:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(rows)


def curate_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in candidates:
        term = str(item.get("phrase") or item.get("term") or "").strip()
        if not _keep(term):
            continue
        lang = str(item.get("lang") or detect_lang(term))
        out.append(
            {
                "schema_version": 1,
                "phrase": term,
                "lang": lang,
                "category": _category(term, lang),
                "aliases": _aliases(term),
                "count": int(item.get("count", 1) or 1),
                "score": float(item.get("score", 1.0) or 1.0),
                "sources": sorted(set(item.get("sources", []) or ["candidates"])),
                "snippets": item.get("snippets", [])[:3],
                "decision": "keep",
                "curation_mode": "heuristic",
            }
        )
    return out


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _keep(term: str) -> bool:
    if is_secret(term):
        return False
    if SHORT_HEX.match(term):
        return False
    if len(term) < 2 or len(term) > 80:
        return False
    if term.count("/") or term.count("\\"):
        return False
    if term.startswith(("-", ".")) or term.endswith(("-", ".")):
        return False
    if not any(char.isalpha() or "\u4e00" <= char <= "\u9fff" for char in term):
        return False
    return True


def _category(term: str, lang: str) -> str:
    if CAMEL.match(term) or ALL_CAPS.match(term):
        return "acronym" if ALL_CAPS.match(term) else "library"
    if lang in {"zh", "mixed"} and any("\u4e00" <= char <= "\u9fff" for char in term):
        return "domain"
    if ID_LIKE.match(term):
        return "id"
    return "domain"


def _aliases(term: str) -> list[str]:
    aliases = []
    lower = term.lower()
    if lower != term and (CAMEL.match(term) or ALL_CAPS.match(term)):
        aliases.append(lower)
    return aliases
