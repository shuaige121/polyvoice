"""Extract deterministic vocabulary candidates from scanned user text."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import jieba
from wordfreq import zipf_frequency

from polyvoice.vocab.secrets import is_secret, redact


STOP_EN = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "should",
    "could",
    "can",
    "may",
    "might",
    "must",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "this",
    "that",
    "these",
    "those",
    "and",
    "or",
    "but",
    "if",
    "then",
    "else",
    "when",
    "where",
    "why",
    "how",
    "what",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "from",
    "by",
    "as",
    "about",
    "not",
    "no",
    "yes",
    "ok",
    "okay",
    "http",
    "https",
    "www",
    "com",
    "org",
}

CAMEL_OR_ACRONYM = re.compile(r"\b[A-Z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b|\b[A-Z]{2,}\b")
ASCII_TERM = re.compile(r"\b[A-Za-z][A-Za-z0-9_.-]{1,}[A-Za-z0-9]\b")
TOKEN_SPLIT = re.compile(r"\s+")


def default_candidates_out() -> Path:
    return Path("vocab/candidates.jsonl")


def default_review_out() -> Path:
    return Path("vocab/candidates_review.md")


def default_extract_out() -> Path:
    return default_candidates_out()


def extract(
    input_path: Path,
    out: Path = default_candidates_out(),
    review_out: Path = default_review_out(),
    *,
    limit: int = 400,
    strict_redact: bool = True,
    dry_run: bool = False,
) -> int:
    records = _read_scan(input_path)
    candidates = build_candidates(records, limit=limit, strict_redact=strict_redact)
    if dry_run:
        return len(candidates)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for item in candidates:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    review_out.parent.mkdir(parents=True, exist_ok=True)
    review_out.write_text(render_review(candidates), encoding="utf-8")
    return len(candidates)


def build_candidates(
    records: list[dict[str, Any]], *, limit: int = 400, strict_redact: bool = True
) -> list[dict[str, Any]]:
    tf: Counter[str] = Counter()
    snippets: dict[str, list[dict[str, str]]] = defaultdict(list)
    sources: dict[str, set[str]] = defaultdict(set)
    camel_bonus: Counter[str] = Counter()

    for record in records:
        text = str(record.get("text", ""))
        session_id = str(record.get("session_id", ""))
        for token in jieba.lcut(text):
            _add_token(token, record, tf, snippets, sources, strict_redact=strict_redact)
        for match in CAMEL_OR_ACRONYM.findall(text):
            camel_bonus[match] += 1
            _add_token(match, record, tf, snippets, sources, strict_redact=strict_redact)
        for match in ASCII_TERM.findall(text):
            if match not in tf:
                continue
            sources[match].add(session_id)

    ranked: list[dict[str, Any]] = []
    for term, count in tf.items():
        if count < 2 or is_secret(term) or not _valid_term(term):
            continue
        zipf = term_zipf(term)
        if zipf >= 4.5:
            continue
        score = count * max(0.5, 8.0 - zipf)
        camel = term in camel_bonus
        if camel:
            score *= 1.5
        lang = detect_lang(term)
        ranked.append(
            {
                "schema_version": 1,
                "term": term,
                "phrase": term,
                "lang": lang,
                "score": round(score, 3),
                "count": count,
                "zipf": round(zipf, 3),
                "camel": camel,
                "sources": sorted(source for source in sources[term] if source),
                "snippets": snippets[term][:3],
            }
        )

    ranked.sort(key=lambda item: (-float(item["score"]), str(item["term"]).lower()))
    return ranked[:limit]


def render_review(candidates: list[dict[str, Any]]) -> str:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        grouped[(str(item["lang"]), _score_band(float(item["score"])))].append(item)

    lines = ["# Vocab Candidate Review", ""]
    for key in sorted(grouped, key=lambda value: (value[0], value[1])):
        lang, band = key
        lines.extend([f"## {lang} / {band}", "", "| term | score | count | zipf | snippets |", "|---|---:|---:|---:|---|"])
        for item in grouped[key]:
            snippet = "<br>".join(_escape_md(s["text"]) for s in item.get("snippets", [])[:3])
            lines.append(
                f"| {_escape_md(str(item['term']))} | {item['score']} | {item['count']} | {item['zipf']} | {snippet} |"
            )
        lines.append("")
    return "\n".join(lines)


def detect_lang(term: str) -> str:
    has_cjk = any("\u4e00" <= char <= "\u9fff" for char in term)
    has_ascii = any("A" <= char <= "z" for char in term)
    if has_cjk and has_ascii:
        return "mixed"
    if has_cjk:
        return "zh"
    return "en"


def term_zipf(term: str) -> float:
    if detect_lang(term) == "zh":
        return zipf_frequency(term, "zh")
    return max(zipf_frequency(term, "en"), zipf_frequency(term.lower(), "en"))


def _read_scan(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = str(item.get("text", "")).strip()
            if text:
                records.append(item)
    return records


def _add_token(
    token: str,
    record: dict[str, Any],
    tf: Counter[str],
    snippets: dict[str, list[dict[str, str]]],
    sources: dict[str, set[str]],
    *,
    strict_redact: bool,
) -> None:
    term = token.strip()
    if not term or term.isdigit() or is_secret(term) or not _valid_term(term):
        return
    tf[term] += 1
    session_id = str(record.get("session_id", ""))
    sources[term].add(session_id)
    if len(snippets[term]) < 3:
        text = _snippet(str(record.get("text", "")), term, strict_redact=strict_redact)
        if text:
            snippets[term].append({"session_id": session_id, "text": text})


def _valid_term(term: str) -> bool:
    if all(not char.isalnum() and not ("\u4e00" <= char <= "\u9fff") for char in term):
        return False
    if detect_lang(term) == "zh":
        return len(term) >= 2
    return len(term) >= 2 and term.lower() not in STOP_EN and any(char.isalpha() for char in term)


def _snippet(text: str, term: str, *, strict_redact: bool) -> str:
    text = redact(text) if strict_redact else text
    idx = text.lower().find(term.lower())
    if idx < 0:
        return text[:80]
    start = max(0, idx - 30)
    end = min(len(text), idx + len(term) + 30)
    return TOKEN_SPLIT.sub(" ", text[start:end]).strip()[:80]


def _score_band(score: float) -> str:
    if score >= 30:
        return "high"
    if score >= 12:
        return "medium"
    return "low"


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
