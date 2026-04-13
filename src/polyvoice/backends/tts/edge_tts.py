"""edge-tts backend adapter."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any, Iterator


ALIASES = {
    "f1": "zh-CN-XiaoxiaoNeural",
    "m1": "zh-CN-YunxiNeural",
    "en-f1": "en-US-AriaNeural",
}
DEFAULT_VOICES = [
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-YunxiNeural",
    "en-US-AriaNeural",
]


class EdgeTTSBackend:
    name = "edge_tts"
    sample_rate = 24000

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}

    def list_voices(self) -> list[str]:
        return sorted({*ALIASES, *DEFAULT_VOICES})

    def stream(self, text: str, voice: str, speed: float = 1.0) -> Iterator[bytes]:
        resolved = ALIASES.get(voice, voice)
        if resolved not in DEFAULT_VOICES and voice not in DEFAULT_VOICES:
            raise ValueError(f"unknown voice: {voice}")
        mp3 = asyncio.run(self._synthesize_mp3(text, resolved, speed))
        yield from self._decode_mp3(mp3)

    async def _synthesize_mp3(self, text: str, voice: str, speed: float) -> bytes:
        import edge_tts

        rate = f"{round((speed - 1.0) * 100):+d}%"
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    def _decode_mp3(self, mp3: bytes) -> Iterator[bytes]:
        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                str(self.sample_rate),
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(mp3)
        proc.stdin.close()
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            yield chunk
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"ffmpeg exited {code}")
