"""Generate backend hotword adapter files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def generate(vocab_dir: Path = Path("vocab")) -> dict[str, Path]:
    entries = list(_read_master(vocab_dir / "master.jsonl"))
    out_dir = vocab_dir / "adapters"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "sensevoice": out_dir / "sensevoice.txt",
        "sherpa_onnx": out_dir / "sherpa_onnx.txt",
        "capswriter_hot_en": out_dir / "capswriter_hot_en.txt",
        "capswriter_hot_zh": out_dir / "capswriter_hot_zh.txt",
        "capswriter_hot_rule": out_dir / "capswriter_hot_rule.txt",
    }
    files["sensevoice"].write_text("\n".join(item["phrase"] for item in entries) + "\n", encoding="utf-8")
    files["sherpa_onnx"].write_text(
        "\n".join(f'{item["phrase"]} :{item.get("weight", 1.0):.2f}' for item in entries) + "\n",
        encoding="utf-8",
    )
    files["capswriter_hot_en"].write_text(
        "\n".join(item["phrase"] for item in entries if item.get("lang") == "en") + "\n",
        encoding="utf-8",
    )
    files["capswriter_hot_zh"].write_text(
        "\n".join(item["phrase"] for item in entries if item.get("lang") == "zh") + "\n",
        encoding="utf-8",
    )
    rules = []
    for item in entries:
        for alias in item.get("aliases", []):
            rules.append(f'{alias}\t{item["phrase"]}')
    files["capswriter_hot_rule"].write_text("\n".join(rules) + ("\n" if rules else ""), encoding="utf-8")
    return files


def _read_master(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            item: dict[str, Any] = json.loads(line)
            yield item
