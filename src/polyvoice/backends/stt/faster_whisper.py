"""Optional faster-whisper fallback adapter."""

from __future__ import annotations

from typing import Any

import numpy as np

from polyvoice.backends.stt.base import Transcript


class FasterWhisperBackend:
    name = "faster_whisper"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("faster-whisper is not installed") from exc
        opts = options or {}
        self.model = WhisperModel(
            str(opts.get("model", "small")),
            device=str(opts.get("device", "cpu")),
            compute_type=str(opts.get("compute_type", "int8")),
        )

    def transcribe(
        self,
        pcm: bytes,
        sample_rate: int,
        hotwords: list[str] | None = None,
        language: str | None = None,
    ) -> Transcript:
        if sample_rate != 16000:
            raise ValueError("faster_whisper worker expects 16kHz PCM")
        prompt = " ".join(hotwords or []) or None
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        segments, info = self.model.transcribe(samples, language=None if language == "auto" else language, initial_prompt=prompt)
        out = [{"start": seg.start, "end": seg.end, "text": seg.text} for seg in segments]
        return Transcript(text="".join(item["text"] for item in out).strip(), language=info.language, segments=out)
