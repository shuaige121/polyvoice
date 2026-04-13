"""Generate backend hotword adapter files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MAX_PHRASE_LEN = 80


def generate(vocab_dir: Path = Path("vocab"), *, dry_run: bool = False) -> dict[str, Path]:
    entries = list(_dedupe(_read_master(vocab_dir / "master.jsonl")))
    out_dir = vocab_dir / "adapters"
    files = {
        "sensevoice": out_dir / "sensevoice.txt",
        "sherpa_onnx": out_dir / "sherpa_onnx.txt",
        "capswriter_hot_en": out_dir / "capswriter_hot_en.txt",
        "capswriter_hot_zh": out_dir / "capswriter_hot_zh.txt",
        "capswriter_hot_rule": out_dir / "capswriter_hot_rule.txt",
    }
    if dry_run:
        return files
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_lines(files["sensevoice"], [item["phrase"] for item in entries])
    _write_lines(files["sherpa_onnx"], [f'{item["phrase"]} :{item.get("weight", 1.0):.2f}' for item in entries])
    _write_lines(files["capswriter_hot_en"], [item["phrase"] for item in entries if item.get("lang") == "en"])
    _write_lines(files["capswriter_hot_zh"], [item["phrase"] for item in entries if item.get("lang") == "zh"])
    rules = []
    for item in entries:
        for alias in item.get("aliases", []):
            alias = str(alias).strip()
            if _valid_phrase(alias):
                rules.append(f'{alias}\t{item["phrase"]}')
    _write_lines(files["capswriter_hot_rule"], sorted(set(rules)))
    return files


def _read_master(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                item: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            phrase = str(item.get("phrase", "")).strip()
            if _valid_phrase(phrase):
                item["phrase"] = phrase
                yield item


def _dedupe(entries) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for item in entries:
        lang = str(item.get("lang", "mixed"))
        key = item["phrase"] if lang == "zh" else item["phrase"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _valid_phrase(phrase: str) -> bool:
    return 1 < len(phrase) <= MAX_PHRASE_LEN and "\n" not in phrase and "\t" not in phrase


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
