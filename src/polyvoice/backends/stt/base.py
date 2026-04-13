"""STT backend protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Transcript:
    text: str
    language: str | None = None
    segments: list[dict] | None = None  # [{start, end, text}]


@runtime_checkable
class STTBackend(Protocol):
    name: str

    def transcribe(
        self,
        pcm: bytes,
        sample_rate: int,
        hotwords: list[str] | None = None,
        language: str | None = None,
    ) -> Transcript:
        """Transcribe mono PCM16LE audio. `hotwords` bias recognition toward
        user-specific terms; `language` is an ISO code hint (None = auto).
        """
        ...
