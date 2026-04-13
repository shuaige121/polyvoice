"""Claude Code Stop hook that speaks the last assistant response."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from polyvoice.config import ROOT, load_config
from polyvoice.voice_mode import is_active

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def strip_markdown(text: str) -> str:
    text = FENCE_RE.sub("", text)
    text = LINK_RE.sub(r"\1", text)
    text = re.sub(r"[*#_`>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def code_ratio(text: str) -> float:
    if not text:
        return 0.0
    code_chars = sum(1 for char in text if char in "{}[]();=<>/\\|")
    return code_chars / len(text)


def last_assistant_message(transcript: Path) -> str:
    last = ""
    with transcript.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = payload.get("message", payload)
            if message.get("role") == "assistant":
                text = _content_to_text(message.get("content"))
                if text:
                    last = text
    return last


def recent_bash_called_say_zh(transcript: Path, limit: int = 80) -> bool:
    try:
        lines = transcript.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return False
    return any(re.search(r"\bsay-zh\b", line) and "Bash" in line for line in lines)


def summarize(text: str) -> str:
    config = load_config()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return text[: config.voice_mode.max_tts_chars]
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json={
            "model": config.voice_mode.summarize_model,
            "max_tokens": 200,
            "messages": [{"role": "user", "content": f"Summarize for spoken Chinese in <=150 chars:\n{text}"}],
        },
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"].strip()


def play_chime() -> None:
    chime = ROOT / "assets/chime.wav"
    if chime.exists():
        subprocess.run(["ffplay", "-loglevel", "quiet", "-nodisp", "-autoexit", str(chime)], check=False)


def speak(text: str) -> None:
    url = os.environ.get("POLYVOICE_URL", "http://127.0.0.1:7891")
    with httpx.stream(
        "POST",
        f"{url}/v1/audio/speech",
        json={"model": "polyvoice", "input": text, "voice": "f1", "response_format": "wav"},
        timeout=None,
    ) as response:
        response.raise_for_status()
        player = subprocess.Popen(
            ["ffplay", "-loglevel", "quiet", "-nodisp", "-autoexit", "-i", "-"],
            stdin=subprocess.PIPE,
        )
        assert player.stdin is not None
        for chunk in response.iter_bytes():
            player.stdin.write(chunk)
        player.stdin.close()
        player.wait()


def main() -> None:
    if not is_active():
        return
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return
    transcript = Path(transcript_path).expanduser()
    if recent_bash_called_say_zh(transcript):
        return
    text = strip_markdown(last_assistant_message(transcript))
    if not text:
        return
    config = load_config()
    ratio = code_ratio(text)
    if ratio > 0.4:
        play_chime()
        return
    if len(text) > config.voice_mode.max_tts_chars:
        text = summarize(text)
    speak(text)


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
        return "\n".join(parts)
    return ""


if __name__ == "__main__":
    main()
