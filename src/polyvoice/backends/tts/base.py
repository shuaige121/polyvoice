"""TTS backend protocol.

Every TTS adapter implements this. Server spawns the adapter in its own venv
as a subprocess worker; the subprocess `worker.py` entrypoint instantiates the
backend and serves JSON-over-stdio requests.
"""

from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable


@runtime_checkable
class TTSBackend(Protocol):
    name: str
    sample_rate: int  # Hz; backend's native output rate

    def list_voices(self) -> list[str]:
        """Return voice names this backend exposes."""
        ...

    def stream(
        self,
        text: str,
        voice: str,
        speed: float = 1.0,
    ) -> Iterator[bytes]:
        """Yield PCM16LE mono chunks at `sample_rate`. Must start yielding ASAP
        for low first-packet latency; do not buffer the whole utterance.
        """
        ...
