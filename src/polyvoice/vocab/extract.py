"""Extract vocabulary phrases via Anthropic."""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


PROMPT = """You extract domain vocabulary from user/assistant messages for ASR hotword biasing.
Return ONLY JSON array. For each phrase output {"phrase": str, "lang": "zh"|"en"|"mixed", "category": "library"|"command"|"project"|"person"|"acronym"|"domain"}.
Include: library/framework names, CLI commands, project codenames, file path fragments, acronyms (MOM, MOH, RAG), Chinese proper nouns, dictionary-rare technical terms.
Exclude: common words, numbers, URLs, email addresses."""


def default_extract_out() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("vocab/sources") / f"phrases-{stamp}.jsonl"


async def extract(input_path: Path, out: Path, parallel: int, model: str) -> int:
    sessions = _load_sessions(input_path)
    shards = [sessions[i : i + 20] for i in range(0, len(sessions), 20)]
    semaphore = asyncio.Semaphore(parallel)
    out.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        tasks = [_extract_shard(client, semaphore, shard, model) for shard in shards]
        for shard_results in await asyncio.gather(*tasks):
            results.extend(shard_results)

    with out.open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(results)


def _load_sessions(input_path: Path) -> list[dict[str, str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    with input_path.open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            grouped[str(item["session_id"])].append(f'{item["role"]}: {item["text"]}')
    return [{"session_id": key, "text": "\n".join(values)} for key, values in grouped.items()]


async def _extract_shard(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    shard: list[dict[str, str]],
    model: str,
) -> list[dict[str, Any]]:
    async with semaphore:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is required")
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": f"{PROMPT}\n\n{json.dumps(shard, ensure_ascii=False)}"}],
            },
        )
        response.raise_for_status()
        content = response.json()["content"][0]["text"]
        parsed = json.loads(content)
        return [dict(item, sources=[entry["session_id"] for entry in shard]) for item in parsed]
