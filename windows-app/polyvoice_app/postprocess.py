"""STT post-processing: rewrite recognized text using hotword variants.

For SenseVoice (CTC topology) sherpa-onnx does not support hotword biasing
through `from_sense_voice`. As a pragmatic fix we apply find/replace after
recognition: each canonical hotword is matched against the spoken-form
variants the recognizer is most likely to emit, and replaced with the
canonical spelling.

This handles the common cases observed in smoke testing:

    polyvoice    -> "poly voice"
    CosyVoice3   -> "cosy voice 3", "cosy voice3"
    PowerShell   -> "power shell"

It is intentionally simple. For anything fancier (phonetic / pinyin matching)
plug a real fuzzy matcher.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

from polyvoice_app import paths

logger = logging.getLogger("polyvoice.postprocess")

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")
_LETTER_DIGIT = re.compile(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")


def _variants(canonical: str, aliases: list[str] | None = None) -> list[str]:
    """Generate plausible spoken/recognized forms for one canonical hotword."""
    out: set[str] = set()
    out.add(canonical)
    out.add(canonical.lower())
    # CamelCase split, keep digits attached: CosyVoice3 -> "Cosy Voice3"
    camel_split = _CAMEL_BOUNDARY.sub(" ", canonical)
    out.add(camel_split)
    out.add(camel_split.lower())
    # CamelCase + letter/digit split: CosyVoice3 -> "Cosy Voice 3"
    full_split = _LETTER_DIGIT.sub(" ", camel_split)
    out.add(full_split)
    out.add(full_split.lower())
    if "_" in canonical:
        out.add(canonical.replace("_", " "))
        out.add(canonical.replace("_", " ").lower())
    if "-" in canonical:
        out.add(canonical.replace("-", " "))
        out.add(canonical.replace("-", " ").lower())
    # User-provided aliases (from master.jsonl) — for cases like
    # "polyvoice" -> "poly voice" that we cannot auto-derive.
    for alias in aliases or []:
        out.add(alias)
        out.add(alias.lower())
    out.discard("")
    # Sort longest first so longer matches win over their substrings.
    return sorted(out, key=lambda s: -len(s))


@lru_cache(maxsize=8)
def _load_hotwords(path_str: str, mtime: float) -> list[tuple[str, tuple[str, ...]]]:
    del mtime  # cache key only
    path = Path(path_str)
    if not path.exists():
        return []
    items: list[tuple[str, tuple[str, ...]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append((line, ()))
    return items


def load_hotwords(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    """Load and cache hotwords keyed by file mtime. Returns
    [(phrase, aliases_tuple), ...] so callers can also pass aliases.
    """
    if not path.exists():
        return []
    return _load_hotwords(str(path), path.stat().st_mtime)


@lru_cache(maxsize=8)
def _load_master_aliases(path_str: str, mtime: float) -> dict[str, tuple[str, ...]]:
    del mtime
    import json

    out: dict[str, tuple[str, ...]] = {}
    path = Path(path_str)
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            phrase = entry.get("phrase")
            aliases = entry.get("aliases") or []
            if phrase and aliases:
                out[phrase] = tuple(aliases)
    return out


def load_master_aliases(path: Path) -> dict[str, tuple[str, ...]]:
    if not path.exists():
        return {}
    return _load_master_aliases(str(path), path.stat().st_mtime)


def apply_hotwords(text: str, hotwords: list[str], aliases_map: dict[str, tuple[str, ...]] | None = None) -> str:
    """Rewrite STT text by substituting recognized variants with canonical
    spelling. Pure string replace, case-insensitive at word boundaries.
    """
    if not text or not hotwords:
        return text
    aliases_map = aliases_map or {}
    out = text
    # Sort hotwords by length desc so longer canonical matches win.
    for canonical in sorted(hotwords, key=lambda s: -len(s)):
        aliases = list(aliases_map.get(canonical, ()))
        for variant in _variants(canonical, aliases=aliases):
            if variant == canonical:
                continue
            # ASCII boundaries: re's \b treats CJK as word chars in Unicode
            # mode, so "poly voice" between Chinese chars never matches.
            # Use explicit ASCII-only lookarounds.
            if variant.isascii():
                pattern = re.compile(
                    r"(?<![A-Za-z0-9_])" + re.escape(variant) + r"(?![A-Za-z0-9_])",
                    re.IGNORECASE,
                )
            else:
                pattern = re.compile(re.escape(variant))
            out = pattern.sub(canonical, out)
    return out


def process_text(
    text: str,
    hotwords_file: Path | None = None,
    master_file: Path | None = None,
) -> str:
    """Apply configured hotwords and master aliases to recognized text."""
    hotwords_file = hotwords_file or paths.hotwords_path()
    master_file = master_file or paths.master_vocab_path()
    hotword_items = load_hotwords(hotwords_file)
    aliases_map = load_master_aliases(master_file)
    hotwords = [phrase for phrase, _aliases in hotword_items]
    out = apply_hotwords(text, hotwords, aliases_map)
    logger.info(
        "postprocess complete",
        extra={
            "event": "postprocess_complete",
            "hotwords": len(hotwords),
            "changed": out != text,
        },
    )
    return out
